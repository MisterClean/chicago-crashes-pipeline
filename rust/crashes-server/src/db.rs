//! Small RAII boundary over the stable DuckDB C API, pinned at runtime to 2.0.0.
//!
//! All handles stay under one mutex. Transactions give callers a borrowed session
//! so a job cannot accidentally release admission between its statements.

use anyhow::{Context, Result, anyhow, bail, ensure};
use libloading::Library;
use serde_json::{Map, Value};
use std::{
    ffi::{CStr, CString, c_char, c_void},
    fs::{File, OpenOptions},
    path::{Path, PathBuf},
    ptr,
    sync::{
        Arc, Mutex,
        atomic::{AtomicU64, Ordering},
    },
};

type Handle = *mut c_void;
#[repr(C)]
#[derive(Default)]
struct RawResult {
    columns: u64,
    rows: u64,
    changed: u64,
    old_columns: Handle,
    old_error: *mut c_char,
    internal: Handle,
}

macro_rules! api {
    ($($field:ident: $symbol:literal => $ty:ty),* $(,)?) => {
        struct Api { _library: Library, $($field: $ty),* }
        impl Api {
            fn load(path: &Path) -> Result<Self> {
                // SAFETY: only a configured, locally installed DuckDB library is loaded;
                // symbols have the signatures from the pinned v2.0.0 duckdb.h.
                unsafe {
                    let library = Library::new(path).context("load DuckDB shared library")?;
                    $(let $field = *library.get::<$ty>(concat!($symbol, "\0").as_bytes())?;)*
                    Ok(Self { _library: library, $($field),* })
                }
            }
        }
    }
}

api! {
    version: "duckdb_library_version" => unsafe extern "C" fn() -> *const c_char,
    open: "duckdb_open" => unsafe extern "C" fn(*const c_char, *mut Handle) -> u32,
    close: "duckdb_close" => unsafe extern "C" fn(*mut Handle),
    connect: "duckdb_connect" => unsafe extern "C" fn(Handle, *mut Handle) -> u32,
    disconnect: "duckdb_disconnect" => unsafe extern "C" fn(*mut Handle),
    interrupt: "duckdb_interrupt" => unsafe extern "C" fn(Handle),
    query: "duckdb_query" => unsafe extern "C" fn(Handle, *const c_char, *mut RawResult) -> u32,
    destroy_result: "duckdb_destroy_result" => unsafe extern "C" fn(*mut RawResult),
    result_error: "duckdb_result_error" => unsafe extern "C" fn(*mut RawResult) -> *const c_char,
    column_count: "duckdb_column_count" => unsafe extern "C" fn(*mut RawResult) -> u64,
    row_count: "duckdb_row_count" => unsafe extern "C" fn(*mut RawResult) -> u64,
    column_name: "duckdb_column_name" => unsafe extern "C" fn(*mut RawResult, u64) -> *const c_char,
    column_type: "duckdb_column_type" => unsafe extern "C" fn(*mut RawResult, u64) -> u32,
    column_data: "duckdb_column_data" => unsafe extern "C" fn(*mut RawResult,u64)->Handle,
    value_null: "duckdb_value_is_null" => unsafe extern "C" fn(*mut RawResult, u64, u64) -> bool,
    value_varchar: "duckdb_value_varchar" => unsafe extern "C" fn(*mut RawResult, u64, u64) -> *mut c_char,
    value_i64: "duckdb_value_int64" => unsafe extern "C" fn(*mut RawResult, u64, u64) -> i64,
    value_u64: "duckdb_value_uint64" => unsafe extern "C" fn(*mut RawResult, u64, u64) -> u64,
    value_f64: "duckdb_value_double" => unsafe extern "C" fn(*mut RawResult, u64, u64) -> f64,
    value_bool: "duckdb_value_boolean" => unsafe extern "C" fn(*mut RawResult, u64, u64) -> bool,
    free: "duckdb_free" => unsafe extern "C" fn(Handle),
    prepare: "duckdb_prepare" => unsafe extern "C" fn(Handle, *const c_char, *mut Handle) -> u32,
    prepare_error: "duckdb_prepare_error" => unsafe extern "C" fn(Handle) -> *const c_char,
    destroy_prepare: "duckdb_destroy_prepare" => unsafe extern "C" fn(*mut Handle),
    nparams: "duckdb_nparams" => unsafe extern "C" fn(Handle) -> u64,
    bind_null: "duckdb_bind_null" => unsafe extern "C" fn(Handle, u64) -> u32,
    bind_bool: "duckdb_bind_boolean" => unsafe extern "C" fn(Handle, u64, bool) -> u32,
    bind_i64: "duckdb_bind_int64" => unsafe extern "C" fn(Handle, u64, i64) -> u32,
    bind_u64: "duckdb_bind_uint64" => unsafe extern "C" fn(Handle, u64, u64) -> u32,
    bind_f64: "duckdb_bind_double" => unsafe extern "C" fn(Handle, u64, f64) -> u32,
    bind_string: "duckdb_bind_varchar_length" => unsafe extern "C" fn(Handle, u64, *const c_char, u64) -> u32,
    execute: "duckdb_execute_prepared" => unsafe extern "C" fn(Handle, *mut RawResult) -> u32,
}

fn cstring(value: &str) -> Result<CString> {
    CString::new(value).context("embedded NUL is not supported")
}
unsafe fn message(pointer: *const c_char) -> String {
    if pointer.is_null() {
        "DuckDB operation failed".into()
    }
    // SAFETY: the caller passes a live DuckDB-owned NUL-terminated string.
    else {
        unsafe { CStr::from_ptr(pointer) }
            .to_string_lossy()
            .into_owned()
    }
}

struct Owner {
    api: Api,
    database: Handle,
    connection: Handle,
    query_timeout: std::time::Duration,
    generation: Arc<AtomicU64>,
}
// SAFETY: handles are never used outside Database's mutex or its borrowed Session;
// DuckDB permits moving connections between threads, but not concurrent use.
unsafe impl Send for Owner {}
impl Drop for Owner {
    fn drop(&mut self) {
        // SAFETY: these handles belong to this Owner and are closed exactly once.
        unsafe {
            if !self.connection.is_null() {
                (self.api.disconnect)(&mut self.connection);
            }
            if !self.database.is_null() {
                (self.api.close)(&mut self.database);
            }
        }
    }
}

/// One process and one serialized connection own the persistent database.
pub struct Database {
    owner: Mutex<Owner>,
    generation: Arc<AtomicU64>,
    _lock: File,
    pub path: PathBuf,
}
/// A connection borrow with admission held for the entire operation.
pub struct Session<'a> {
    owner: &'a Owner,
}

impl Database {
    /// Open the required engine and take a cross-process owner lock.
    pub fn open(
        path: &Path,
        library: &Path,
        memory: &str,
        threads: u32,
        temp: &Path,
    ) -> Result<Self> {
        ensure!(threads > 0 && threads <= 32, "SQL threads must be 1..32");
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::create_dir_all(temp)?;
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(path.with_extension("owner.lock"))?;
        fs2::FileExt::try_lock_exclusive(&lock).context("another process owns this DuckDB file")?;
        let api = Api::load(library)?;
        // SAFETY: version returns a static library-owned string.
        let version = unsafe { message((api.version)()) };
        ensure!(
            version.trim_start_matches('v') == "2.0.0",
            "required DuckDB 2.0.0; loaded {version}"
        );
        let timeout_seconds = std::env::var("DUCKDB_QUERY_TIMEOUT_SECONDS")
            .ok()
            .map(|value| value.parse::<u64>())
            .transpose()
            .context("DUCKDB_QUERY_TIMEOUT_SECONDS must be an integer")?
            .unwrap_or(120);
        ensure!(
            (1..=900).contains(&timeout_seconds),
            "DUCKDB_QUERY_TIMEOUT_SECONDS must be between 1 and 900"
        );
        let generation = Arc::new(AtomicU64::new(0));
        let mut owner = Owner {
            api,
            database: ptr::null_mut(),
            connection: ptr::null_mut(),
            query_timeout: std::time::Duration::from_secs(timeout_seconds),
            generation: generation.clone(),
        };
        let name = cstring(path.to_str().context("database path must be UTF-8")?)?;
        // SAFETY: valid output handle slots and a string live through the call.
        unsafe {
            ensure!(
                (owner.api.open)(name.as_ptr(), &mut owner.database) == 0,
                "cannot open DuckDB database (check file owner/version)"
            );
            ensure!(
                (owner.api.connect)(owner.database, &mut owner.connection) == 0,
                "cannot connect to DuckDB"
            );
        }
        let session = Session { owner: &owner };
        session.execute(&format!("SET threads={threads}"), &[])?;
        for (key, value) in [
            ("memory_limit", memory),
            (
                "temp_directory",
                temp.to_str().context("temp path must be UTF-8")?,
            ),
            ("max_temp_directory_size", "4GB"),
            ("TimeZone", "America/Chicago"),
        ] {
            session.execute(&format!("SET {key}={}", sql_literal(value)), &[])?;
        }
        session.execute("SET preserve_insertion_order=false", &[])?;
        session.execute("SET autoinstall_known_extensions=false", &[])?;
        Ok(Self {
            owner: Mutex::new(owner),
            generation,
            _lock: lock,
            path: path.to_owned(),
        })
    }
    /// Cache epoch advances before a journaled mutation can commit. No SQL needed.
    pub fn generation(&self) -> u64 {
        self.generation.load(Ordering::Acquire)
    }

    /// Serialize a group of operations on the owning connection.
    pub fn with_session<T>(&self, f: impl FnOnce(&Session<'_>) -> Result<T>) -> Result<T> {
        let owner = self
            .owner
            .lock()
            .map_err(|_| anyhow!("database mutex poisoned"))?;
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            f(&Session { owner: &owner })
        }))
        .map_err(|_| anyhow!("database callback panicked"))?
    }
    /// Commit the callback atomically; roll back any error before releasing admission.
    pub fn transaction<T>(&self, f: impl FnOnce(&Session<'_>) -> Result<T>) -> Result<T> {
        self.with_session(|session| {
            session.execute("BEGIN TRANSACTION", &[])?;
            let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| f(session)))
                .unwrap_or_else(|_| Err(anyhow!("database transaction callback panicked")));
            match outcome {
                Ok(value) => {
                    if let Err(error) = session.execute("COMMIT", &[]) {
                        let _ = session.execute("ROLLBACK", &[]);
                        return Err(error);
                    }
                    Ok(value)
                }
                Err(error) => {
                    let _ = session.execute("ROLLBACK", &[]);
                    Err(error)
                }
            }
        })
    }
    /// Query bounded API results. Use native COPY for large exports.
    pub fn query(&self, sql: &str, params: &[Value]) -> Result<Vec<Value>> {
        self.with_session(|s| s.query(sql, params))
    }
    /// Execute a statement, without retaining returned rows.
    pub fn execute(&self, sql: &str, params: &[Value]) -> Result<()> {
        self.with_session(|s| s.execute(sql, params))
    }
}

struct ResultGuard<'a> {
    api: &'a Api,
    raw: RawResult,
}
impl Drop for ResultGuard<'_> {
    fn drop(&mut self) {
        unsafe { (self.api.destroy_result)(&mut self.raw) }
    }
}
struct Statement<'a> {
    api: &'a Api,
    raw: Handle,
}
impl Drop for Statement<'_> {
    fn drop(&mut self) {
        unsafe { (self.api.destroy_prepare)(&mut self.raw) }
    }
}

impl Session<'_> {
    /// Run with a scoped watchdog. The check can reject a cancelled lease,
    /// elapsed deadline or exhausted disk budget; admission stays held until join.
    pub fn guarded<T>(
        &self,
        check: impl Fn() -> Result<()> + Send + Sync,
        run: impl FnOnce() -> Result<T>,
    ) -> Result<T> {
        use std::sync::atomic::{AtomicBool, Ordering};
        struct Interrupt {
            connection: Handle,
            function: unsafe extern "C" fn(Handle),
        }
        // SAFETY: DuckDB explicitly allows interrupting a live connection from
        // another thread. Scope joins the watchdog before releasing this session.
        unsafe impl Send for Interrupt {}
        unsafe impl Sync for Interrupt {}
        impl Interrupt {
            fn call(&self) {
                unsafe { (self.function)(self.connection) };
            }
        }
        let interrupt = Interrupt {
            connection: self.owner.connection,
            function: self.owner.api.interrupt,
        };
        let done = AtomicBool::new(false);
        let failure = Mutex::new(None);
        let wake = (Mutex::new(()), std::sync::Condvar::new());
        std::thread::scope(|scope| {
            let watchdog = scope.spawn(|| {
                loop {
                    if done.load(Ordering::Acquire) {
                        break;
                    }
                    let checked = std::panic::catch_unwind(std::panic::AssertUnwindSafe(&check))
                        .unwrap_or_else(|_| Err(anyhow!("database watchdog callback panicked")));
                    if let Err(error) = checked {
                        if let Ok(mut failure) = failure.lock() {
                            *failure = Some(error);
                        }
                        interrupt.call();
                        break;
                    }
                    let guard = match wake.0.lock() {
                        Ok(guard) => guard,
                        Err(_) => break,
                    };
                    if done.load(Ordering::Acquire) {
                        break;
                    }
                    let _wait = wake
                        .1
                        .wait_timeout(guard, std::time::Duration::from_millis(50));
                }
            });
            struct Done<'a> {
                flag: &'a AtomicBool,
                wake: &'a (Mutex<()>, std::sync::Condvar),
            }
            impl Drop for Done<'_> {
                fn drop(&mut self) {
                    let _guard = self.wake.0.lock();
                    self.flag.store(true, Ordering::Release);
                    self.wake.1.notify_all();
                }
            }
            let completed = Done {
                flag: &done,
                wake: &wake,
            };
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(run))
                .unwrap_or_else(|_| Err(anyhow!("database guarded callback panicked")));
            drop(completed);
            watchdog
                .join()
                .map_err(|_| anyhow!("database watchdog panicked"))?;
            if let Some(error) = failure
                .lock()
                .map_err(|_| anyhow!("watchdog mutex poisoned"))?
                .take()
            {
                return Err(error);
            }
            result
        })
    }

    fn run(&self, sql: &str, params: &[Value]) -> Result<ResultGuard<'_>> {
        let started = std::time::Instant::now();
        let timeout = self.owner.query_timeout;
        self.guarded(
            || {
                ensure!(
                    started.elapsed() < timeout,
                    "DuckDB statement execution deadline exceeded"
                );
                Ok(())
            },
            || self.run_native(sql, params),
        )
    }

    fn run_native(&self, sql: &str, params: &[Value]) -> Result<ResultGuard<'_>> {
        let api = &self.owner.api;
        let sql = cstring(sql)?;
        let mut result = ResultGuard {
            api,
            raw: RawResult::default(),
        };
        // SAFETY: all pointers are owned by their RAII guards. Parameters are copied
        // by DuckDB's bind calls and the serialized connection remains live.
        unsafe {
            let status = if params.is_empty() {
                (api.query)(self.owner.connection, sql.as_ptr(), &mut result.raw)
            } else {
                let mut statement = Statement {
                    api,
                    raw: ptr::null_mut(),
                };
                if (api.prepare)(self.owner.connection, sql.as_ptr(), &mut statement.raw) != 0 {
                    bail!("{}", message((api.prepare_error)(statement.raw)));
                }
                ensure!(
                    (api.nparams)(statement.raw) == params.len() as u64,
                    "SQL parameter count mismatch"
                );
                for (index, value) in params.iter().enumerate() {
                    let index = index as u64 + 1;
                    let status = match value {
                        Value::Null => (api.bind_null)(statement.raw, index),
                        Value::Bool(value) => (api.bind_bool)(statement.raw, index, *value),
                        Value::Number(value) if value.is_i64() => {
                            (api.bind_i64)(statement.raw, index, value.as_i64().context("integer")?)
                        }
                        Value::Number(value) if value.is_u64() => {
                            (api.bind_u64)(statement.raw, index, value.as_u64().context("integer")?)
                        }
                        Value::Number(value) => {
                            (api.bind_f64)(statement.raw, index, value.as_f64().context("number")?)
                        }
                        Value::String(value) => (api.bind_string)(
                            statement.raw,
                            index,
                            value.as_ptr().cast(),
                            value.len() as u64,
                        ),
                        value => {
                            let text = serde_json::to_string(value)?;
                            (api.bind_string)(
                                statement.raw,
                                index,
                                text.as_ptr().cast(),
                                text.len() as u64,
                            )
                        }
                    };
                    ensure!(status == 0, "DuckDB parameter binding failed");
                }
                (api.execute)(statement.raw, &mut result.raw)
            };
            if status != 0 {
                bail!("{}", message((api.result_error)(&mut result.raw)));
            }
        }
        Ok(result)
    }
    /// Run native SQL, retaining no result collection in Rust.
    pub fn execute(&self, sql: &str, params: &[Value]) -> Result<()> {
        // Every facts/layers/deletion publication journals in its transaction.
        // Advance first: failed/rolled-back mutations can evict, never expose stale data.
        if sql
            .trim_start()
            .to_ascii_lowercase()
            .starts_with("insert into rust_mutations ")
        {
            self.owner.generation.fetch_add(1, Ordering::AcqRel);
        }
        self.run(sql, params)?;
        Ok(())
    }
    /// Return bounded rows as typed JSON objects; VARCHAR values remain strings.
    pub fn query(&self, sql: &str, params: &[Value]) -> Result<Vec<Value>> {
        let mut result = self.run(sql, params)?;
        let api = result.api;
        // SAFETY: accessors borrow the live result. Every allocated VARCHAR is freed
        // using the allocating library, before its ResultGuard is dropped.
        unsafe {
            let columns = (api.column_count)(&mut result.raw);
            let rows = (api.row_count)(&mut result.raw);
            ensure!(
                rows <= 100_000,
                "API result exceeded row limit; use COPY for exports"
            );
            let names = (0..columns)
                .map(|c| message((api.column_name)(&mut result.raw, c)))
                .collect::<Vec<_>>();
            let types = (0..columns)
                .map(|c| (api.column_type)(&mut result.raw, c))
                .collect::<Vec<_>>();
            let mut output = Vec::with_capacity(rows as usize);
            for row in 0..rows {
                let mut object = Map::new();
                for column in 0..columns {
                    let value = if (api.value_null)(&mut result.raw, column, row) {
                        Value::Null
                    } else {
                        match types[column as usize] {
                            1 => Value::Bool((api.value_bool)(&mut result.raw, column, row)),
                            2..=5 => Value::from((api.value_i64)(&mut result.raw, column, row)),
                            6..=9 => Value::from((api.value_u64)(&mut result.raw, column, row)),
                            10 | 11 | 19 => {
                                Value::from((api.value_f64)(&mut result.raw, column, row))
                            }
                            31 => {
                                // Pinned duckdb.h declares TIMESTAMP_TZ as duckdb_timestamp
                                // (UTC microseconds). Direct materialized column access avoids
                                // the context-free VARCHAR cast, which fails for this type.
                                let pointer = (api.column_data)(&mut result.raw, column);
                                ensure!(
                                    !pointer.is_null(),
                                    "TIMESTAMPTZ data unavailable; serialize explicitly in SQL"
                                );
                                let micros = std::ptr::read_unaligned(
                                    pointer.cast::<i64>().add(row as usize),
                                );
                                let time=chrono::DateTime::<chrono::Utc>::from_timestamp_micros(micros).context("TIMESTAMPTZ outside supported calendar range; serialize explicitly in SQL")?;
                                Value::String(
                                    time.to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
                                )
                            }
                            42 => bail!("TIMESTAMP_TZ_NS requires explicit SQL serialization"),
                            16 | 32 => {
                                let pointer = (api.value_varchar)(&mut result.raw, column, row);
                                ensure!(!pointer.is_null(), "DuckDB integer conversion failed");
                                let text = message(pointer);
                                (api.free)(pointer.cast());
                                serde_json::from_str(&text).context("integer exceeds JSON range")?
                            }
                            _ => {
                                let pointer = (api.value_varchar)(&mut result.raw, column, row);
                                ensure!(!pointer.is_null(), "DuckDB string conversion failed");
                                let text = message(pointer);
                                (api.free)(pointer.cast());
                                Value::String(text)
                            }
                        }
                    };
                    object.insert(names[column as usize].clone(), value);
                }
                output.push(Value::Object(object));
            }
            Ok(output)
        }
    }
}

/// Quote a trusted SQL literal, including file paths that cannot be parameters.
pub fn sql_literal(value: &str) -> String {
    format!("'{}'", value.replace('\'', "''"))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn sql_literal_escapes_quotes() {
        assert_eq!(sql_literal("a'b"), "'a''b'");
    }
    #[test]
    fn native_statement_deadline_interrupts_and_preserves_connection() {
        let library = crate::test_support::library();
        if !library.is_file() {
            eprintln!("SKIP statement deadline fixture: official DuckDB2 library missing");
            return;
        }
        let directory = tempfile::tempdir().unwrap();
        let db = Database::open(
            &directory.path().join("deadline.duckdb"),
            &library,
            "64MB",
            1,
            &directory.path().join("spill"),
        )
        .unwrap();
        db.owner.lock().unwrap().query_timeout = std::time::Duration::from_millis(50);
        let started = std::time::Instant::now();
        let error = db
            .query(
                "SELECT sum(sqrt(i::DOUBLE)) FROM range(10000000000) t(i)",
                &[],
            )
            .unwrap_err();
        assert_eq!(
            error.to_string(),
            "DuckDB statement execution deadline exceeded"
        );
        assert!(started.elapsed() < std::time::Duration::from_secs(3));
        assert_eq!(db.query("SELECT 42 AS n", &[]).unwrap()[0]["n"], 42);
    }
    #[test]
    fn native_timestamptz_scalars_preserve_utc_microseconds_without_context_casts() {
        let library = crate::test_support::library();
        if !library.is_file() {
            eprintln!("SKIP TIMESTAMPTZ fixture: official DuckDB2 library missing");
            return;
        }
        let directory = tempfile::tempdir().unwrap();
        let db = Database::open(
            &directory.path().join("timestamp.duckdb"),
            &library,
            "64MB",
            1,
            &directory.path().join("spill"),
        )
        .unwrap();
        let rows=db.query("SELECT now() AS current, '2024-02-01 05:59:59.123456+00'::TIMESTAMPTZ AS fixed, NULL::TIMESTAMPTZ AS missing",&[]).unwrap();
        assert_eq!(rows[0]["fixed"], "2024-02-01T05:59:59.123456Z");
        assert!(chrono::DateTime::parse_from_rfc3339(rows[0]["current"].as_str().unwrap()).is_ok());
        assert!(rows[0]["missing"].is_null());
        assert!(
            db.query("SELECT 'infinity'::TIMESTAMPTZ AS unsupported", &[])
                .unwrap_err()
                .to_string()
                .contains("outside supported calendar range")
        );
    }
}
