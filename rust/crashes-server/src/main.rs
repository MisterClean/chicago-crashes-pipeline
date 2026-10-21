//! Single-owner Rust API, ingestion, spatial data and durable export service.
mod admin;
mod api;
#[cfg(test)]
mod api_tests;
mod cache;
mod compat;
mod control;
mod db;
mod exports;
mod ingestion;
mod layers;
mod migration;
mod mutations;
mod queries;
mod recovery;
#[cfg(test)]
mod recovery_tests;
mod sources;
mod storage;
#[cfg(test)]
mod test_support;
mod worker;

use anyhow::{Context, Result, ensure};
use clap::{Parser, Subcommand};
use std::{
    net::IpAddr,
    path::{Path, PathBuf},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
};

#[derive(Parser)]
#[command(
    version,
    about = "Chicago crashes: Rust + DuckDB 2.0 single-owner service"
)]
struct Options {
    #[arg(long, env = "DATA_DIR", default_value = ".local/data")]
    data_dir: PathBuf,
    #[arg(long, env = "DUCKDB_DATABASE")]
    database: Option<PathBuf>,
    #[arg(long, env = "DUCKDB_LIBRARY_PATH")]
    library: Option<PathBuf>,
    #[arg(
        long,
        env = "DUCKDB_SPATIAL_PATH",
        default_value = ".local/rust-duckdb/spatial.duckdb_extension"
    )]
    spatial: PathBuf,
    #[arg(long, env = "DUCKDB_MEMORY_LIMIT", default_value = "256MB")]
    memory_limit: String,
    #[arg(long, env = "DUCKDB_THREADS", default_value_t = 2)]
    threads: u32,
    #[command(subcommand)]
    command: Command,
}
#[derive(Subcommand)]
enum Command {
    BuildInfo,
    Probe,
    Inspect,
    Download {
        #[arg(long)]
        directory: PathBuf,
        #[arg(
            long,
            value_delimiter = ',',
            default_value = "crashes,people,vehicles,fatalities"
        )]
        datasets: Vec<String>,
        #[arg(long)]
        api: bool,
    },
    Seed {
        #[arg(long)]
        source_dir: PathBuf,
        #[arg(
            long,
            value_delimiter = ',',
            default_value = "crashes,people,vehicles,fatalities"
        )]
        datasets: Vec<String>,
        #[arg(long)]
        profiling: bool,
        #[arg(long)]
        operation_id: Option<String>,
    },
    ImportLayers {
        #[arg(long)]
        snapshot: PathBuf,
    },
    ExportPostgresSnapshot {
        #[arg(long)]
        output: PathBuf,
        #[arg(long)]
        allow_production_read: bool,
    },
    ImportFactSnapshot {
        #[arg(long)]
        snapshot: PathBuf,
    },
    ImportLegacyControl {
        #[arg(long)]
        snapshot: PathBuf,
    },
    Backup {
        #[arg(long)]
        output: PathBuf,
    },
    Restore {
        #[arg(long)]
        snapshot: PathBuf,
    },
    ExportControl {
        #[arg(long)]
        output: PathBuf,
    },
    ImportControl {
        #[arg(long)]
        input: PathBuf,
    },
    Serve {
        #[arg(long, env = "BIND_ADDRESS", default_value = "127.0.0.1")]
        bind: IpAddr,
        #[arg(long, env = "PORT", default_value_t = 8003)]
        port: u16,
        #[arg(long, env = "APP_ENV", default_value = "development")]
        environment: String,
        #[arg(long)]
        allow_profiling_data: bool,
        #[arg(long, env = "DAILY_SYNC", default_value_t = false)]
        daily_sync: bool,
    },
}

fn open(options: &Options) -> Result<db::Database> {
    let default = if cfg!(target_os = "macos") {
        ".local/rust-duckdb/libduckdb.dylib"
    } else {
        ".local/rust-duckdb/libduckdb.so"
    };
    let path = options
        .database
        .clone()
        .unwrap_or_else(|| options.data_dir.join("current.duckdb"));
    let db = db::Database::open(
        &path,
        options.library.as_deref().unwrap_or(Path::new(default)),
        &options.memory_limit,
        options.threads,
        &options.data_dir.join("spill"),
    )?;
    db.execute(
        &format!(
            "LOAD {}",
            db::sql_literal(
                options
                    .spatial
                    .canonicalize()?
                    .to_str()
                    .context("extension path UTF-8")?
            )
        ),
        &[],
    )?;
    db.execute("SET geometry_always_xy=true", &[])?;
    Ok(db)
}

fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "crashes_server=info,tower_http=info".into()),
        )
        .json()
        .init();
    let options = Options::parse();
    if matches!(options.command, Command::BuildInfo) {
        println!(
            "{}",
            serde_json::json!({"version":env!("CARGO_PKG_VERSION"),"source_sha256":env!("CRASHES_SOURCE_SHA256"),"engine_required":"2.0.0","arch":std::env::consts::ARCH,"os":std::env::consts::OS})
        );
        return Ok(());
    }
    std::fs::create_dir_all(&options.data_dir)?;
    if let Command::Download {
        directory,
        datasets,
        api,
    } = &options.command
    {
        for dataset in datasets {
            let source = if *api {
                sources::download_api_source(directory, dataset)?
            } else {
                sources::download_source(directory, dataset)?
            };
            println!("{}", serde_json::to_string(&source.manifest)?);
        }
        return Ok(());
    }
    if let Command::Restore { snapshot } = &options.command {
        recovery::restore(snapshot, &options.data_dir)?;
        return Ok(());
    }
    ensure!(
        !options.data_dir.join(".restore-in-progress").exists(),
        "interrupted restore must be resumed before opening this data directory"
    );
    let control = control::ControlStore::open(options.data_dir.join("control.sqlite"), 32, 180)?;
    if let Command::ExportControl { output } = &options.command {
        use std::io::Write;
        let mut create = std::fs::OpenOptions::new();
        create.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            create.mode(0o600);
        }
        create
            .open(output)?
            .write_all(&serde_json::to_vec_pretty(&control.export_snapshot()?)?)?;
        return Ok(());
    }
    if let Command::ImportControl { input } = &options.command {
        let snapshot = serde_json::from_reader(std::fs::File::open(input)?)?;
        control.import_snapshot(&snapshot)?;
        return Ok(());
    }
    if let Command::ImportLegacyControl { snapshot } = &options.command {
        control.import_legacy_directory(snapshot)?;
        return Ok(());
    }
    let database = Arc::new(open(&options)?);
    match &options.command {
        Command::BuildInfo=>{},
        Command::Probe=>println!("{}",serde_json::to_string_pretty(&database.query("SELECT version() AS version, current_setting('memory_limit') AS memory_limit, current_setting('threads') AS sql_threads, ST_Distance_Spheroid(ST_Point(-87.65,41.88), ST_Point(-87.65,41.881)) AS axis_probe_meters",&[])?)?),
        Command::Inspect=>println!("{}",serde_json::to_string_pretty(&database.query("SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name",&[])?)?),
        Command::Seed{source_dir,datasets,profiling,operation_id}=>{
            let receipt=ingestion::publish_sources(&database,source_dir,datasets,if *profiling{sources::PublicationMode::Profiling}else{sources::PublicationMode::Production},operation_id.as_deref().unwrap_or(&uuid::Uuid::new_v4().to_string()))?;
            layers::initialize_catalog(&database)?;
            println!("{receipt}");
        },
        Command::ImportLayers{snapshot}=>println!("{}",layers::import_layer_snapshot(&database,snapshot)?),
        Command::ImportFactSnapshot{snapshot}=>println!("{}",ingestion::import_fact_snapshot(&database,snapshot)?),
        Command::ExportPostgresSnapshot{output,allow_production_read}=>println!("{}",migration::export_postgres_snapshot(&database,output,*allow_production_read,&||Ok(()))?),
        Command::Backup{output}=>println!("{}",recovery::backup(&database,&control,output,storage::ObjectStorage::from_env()?.as_ref())?),
        Command::Serve{bind,port,environment,allow_profiling_data,daily_sync}=> {
            let production=environment=="production";
            ensure!(production||environment=="development","APP_ENV must be development or production");
            let key=std::env::var("API_KEY").unwrap_or_default();
            ensure!(!production||key.len()>=32,"production requires API_KEY of at least 32 bytes");
            ensure!(!*allow_profiling_data||(!production&&bind.is_loopback()),"profiling data is allowed only on a development loopback listener");
            let storage=storage::ObjectStorage::from_env()?.map(Arc::new);
            ensure!(!production||storage.is_some(),"production requires configured private EXPORT_* S3 storage");
            if !*allow_profiling_data {recovery::assert_complete(&database)?;}
            for table in ["crashes","crash_people","crash_vehicles","vision_zero_fatalities","spatial_layers","spatial_layer_features"] {database.query(&format!("SELECT 1 FROM {table} LIMIT 1"),&[])?;}
            control.initialize_scheduling(*daily_sync)?;
            let state=api::AppState { db:database,control,directory:options.data_dir.clone(),api_key:Arc::new(key),production,storage,admission:Arc::new(tokio::sync::Semaphore::new(32)),profiling_data:*allow_profiling_data,pubcache:Arc::new(cache::ResponseCache::from_env()?) };
            let stop=Arc::new(AtomicBool::new(false));
            state.control.recover_interrupted()?;
            mutations::reconcile_deletions(&state.db,&state.control)?;
            let worker=worker::start(state.clone(),stop.clone());
            let runtime=tokio::runtime::Builder::new_multi_thread().worker_threads(2).enable_all().build()?;
            let result=runtime.block_on(async {
                let listener=tokio::net::TcpListener::bind((*bind,*port)).await?;
                tracing::info!(address=%listener.local_addr()?,production,"Rust service listening");
                let shutdown_stop=stop.clone();
                axum::serve(listener,api::router(state)).with_graceful_shutdown(async move {shutdown().await;shutdown_stop.store(true,Ordering::Release);}).await.map_err(anyhow::Error::from)
            });
            stop.store(true,Ordering::Release);
            worker.join().map_err(|_|anyhow::anyhow!("worker thread failed"))?;
            result?;
        },
        Command::Download{..}|Command::Restore{..}|Command::ExportControl{..}|Command::ImportControl{..}|Command::ImportLegacyControl{..}=>{},
    }
    Ok(())
}

async fn shutdown() {
    #[cfg(unix)]
    {
        if let Ok(mut term) =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
        {
            tokio::select! {_=tokio::signal::ctrl_c()=>{},_=term.recv()=>{}};
            return;
        }
    }
    let _ = tokio::signal::ctrl_c().await;
}
