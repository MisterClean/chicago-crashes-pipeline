//! Bounded, generation-scoped serialized public responses.
//!
//! The exact serialized payload byte total is capped. A separate entry bound
//! limits keys/allocator bookkeeping; request bodies are retained only as hashes.
use anyhow::{Context, Result, ensure};
use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    sync::{
        Arc, Mutex,
        atomic::{AtomicU64, Ordering},
    },
    time::{Duration, Instant},
};

pub const MAX_BYTES: usize = 16 * 1024 * 1024;
const MAX_ENTRY_BYTES: usize = 4 * 1024 * 1024;
const MAX_ENTRIES: usize = 256;
pub type Key = [u8; 32];

struct Entry {
    bytes: Arc<[u8]>,
    expires: Instant,
    touched: u64,
}
#[derive(Default)]
struct Entries {
    values: BTreeMap<Key, Entry>,
    bytes: usize,
    clock: u64,
}

/// One cache belongs to one server/database owner and starts empty on restart.
pub struct ResponseCache {
    max_bytes: usize,
    ttl: Duration,
    entries: Mutex<Entries>,
    gate: Arc<tokio::sync::Mutex<()>>,
    waiters: Arc<tokio::sync::Semaphore>,
    hits: AtomicU64,
    misses: AtomicU64,
}

#[derive(Serialize)]
pub struct Stats {
    pub enabled: bool,
    pub entries: usize,
    pub bytes: usize,
    pub max_bytes: usize,
    pub hits: u64,
    pub misses: u64,
}

pub struct FillGuard {
    _gate: tokio::sync::OwnedMutexGuard<()>,
    _waiter: tokio::sync::OwnedSemaphorePermit,
}

impl ResponseCache {
    pub fn from_env() -> Result<Self> {
        let bytes = std::env::var("PUBLIC_CACHE_BYTES")
            .ok()
            .map(|v| v.parse::<usize>())
            .transpose()
            .context("PUBLIC_CACHE_BYTES must be an integer")?
            .unwrap_or(MAX_BYTES);
        ensure!(bytes <= MAX_BYTES, "PUBLIC_CACHE_BYTES must be 0..16777216");
        Ok(Self::new(bytes, Duration::from_secs(300)))
    }

    pub fn new(max_bytes: usize, ttl: Duration) -> Self {
        Self {
            max_bytes: max_bytes.min(MAX_BYTES),
            ttl,
            entries: Mutex::new(Entries::default()),
            gate: Arc::new(tokio::sync::Mutex::new(())),
            waiters: Arc::new(tokio::sync::Semaphore::new(32)),
            hits: AtomicU64::new(0),
            misses: AtomicU64::new(0),
        }
    }

    pub fn enabled(&self) -> bool {
        self.max_bytes > 0 && !self.ttl.is_zero()
    }

    /// Hash every semantic input without retaining large polygons or user dates.
    pub fn key(
        generation: u64,
        method: &str,
        path: &str,
        query: &BTreeMap<String, String>,
        body: &Value,
        time_context: &str,
    ) -> Result<Key> {
        let mut digest = Sha256::new();
        digest.update(serde_json::to_vec(&(
            generation,
            method,
            path,
            query,
            body,
            time_context,
        ))?);
        Ok(digest.finalize().into())
    }

    pub fn get(&self, key: &Key) -> Option<Arc<[u8]>> {
        self.get_at(key, Instant::now())
    }

    fn get_at(&self, key: &Key, now: Instant) -> Option<Arc<[u8]>> {
        if !self.enabled() {
            return None;
        }
        let mut entries = self.entries.lock().ok()?;
        Self::expire(&mut entries, now);
        entries.clock = entries.clock.wrapping_add(1);
        let clock = entries.clock;
        let entry = entries.values.get_mut(key)?;
        entry.touched = clock;
        Some(entry.bytes.clone())
    }

    pub fn insert(&self, key: Key, bytes: Arc<[u8]>) -> bool {
        self.insert_at(key, bytes, Instant::now())
    }

    fn insert_at(&self, key: Key, bytes: Arc<[u8]>, now: Instant) -> bool {
        if !self.enabled() || bytes.len() > MAX_ENTRY_BYTES || bytes.len() > self.max_bytes {
            return false;
        }
        let Ok(mut entries) = self.entries.lock() else {
            return false;
        };
        Self::expire(&mut entries, now);
        if let Some(old) = entries.values.remove(&key) {
            entries.bytes -= old.bytes.len();
        }
        while entries.bytes + bytes.len() > self.max_bytes || entries.values.len() >= MAX_ENTRIES {
            let Some(key) = entries
                .values
                .iter()
                .min_by_key(|(_, v)| v.touched)
                .map(|(key, _)| *key)
            else {
                break;
            };
            if let Some(old) = entries.values.remove(&key) {
                entries.bytes -= old.bytes.len();
            }
        }
        entries.clock = entries.clock.wrapping_add(1);
        let touched = entries.clock;
        entries.bytes += bytes.len();
        entries.values.insert(
            key,
            Entry {
                bytes,
                expires: now + self.ttl,
                touched,
            },
        );
        true
    }

    fn expire(entries: &mut Entries, now: Instant) {
        entries.values.retain(|_, entry| {
            if entry.expires <= now {
                entries.bytes -= entry.bytes.len();
                false
            } else {
                true
            }
        });
    }

    /// Bound both duplicate work and the number of pending public cache fills.
    pub async fn fill_guard(&self) -> Result<FillGuard> {
        let waiter = self
            .waiters
            .clone()
            .try_acquire_owned()
            .context("public cache fill capacity exceeded")?;
        let gate = tokio::time::timeout(Duration::from_secs(60), self.gate.clone().lock_owned())
            .await
            .context("public cache fill wait deadline exceeded")?;
        Ok(FillGuard {
            _gate: gate,
            _waiter: waiter,
        })
    }

    pub fn record_hit(&self) {
        self.hits.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_miss(&self) {
        self.misses.fetch_add(1, Ordering::Relaxed);
    }

    pub fn stats(&self) -> Stats {
        let (entries, bytes) = self
            .entries
            .lock()
            .map(|mut entries| {
                Self::expire(&mut entries, Instant::now());
                (entries.values.len(), entries.bytes)
            })
            .unwrap_or_default();
        Stats {
            enabled: self.enabled(),
            entries,
            bytes,
            max_bytes: self.max_bytes,
            hits: self.hits.load(Ordering::Relaxed),
            misses: self.misses.load(Ordering::Relaxed),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn key(n: u64) -> Key {
        ResponseCache::key(
            n,
            "POST",
            "/dashboard/location-report",
            &BTreeMap::new(),
            &serde_json::json!({"place_type":"layer:4","place_id":"259"}),
            "2026-10-21T12",
        )
        .unwrap()
    }
    #[test]
    fn expires_at_ttl_without_extending_lifetime_on_read() {
        let cache = ResponseCache::new(100, Duration::from_secs(300));
        let now = Instant::now();
        cache.insert_at(key(1), Arc::from(&b"{}"[..]), now);
        assert!(
            cache
                .get_at(&key(1), now + Duration::from_secs(299))
                .is_some()
        );
        assert!(
            cache
                .get_at(&key(1), now + Duration::from_secs(300))
                .is_none()
        );
        assert_eq!(cache.stats().bytes, 0);
    }
    #[test]
    fn byte_budget_evicts_least_recently_used_and_reuses_serialized_bytes() {
        let cache = ResponseCache::new(10, Duration::from_secs(300));
        let bytes: Arc<[u8]> = Arc::from(&b"1234"[..]);
        cache.insert(key(1), bytes.clone());
        cache.insert(key(2), bytes.clone());
        assert!(Arc::ptr_eq(&bytes, &cache.get(&key(1)).unwrap()));
        cache.insert(key(3), bytes);
        assert!(cache.get(&key(2)).is_none());
        assert_eq!(cache.stats().bytes, 8);
        assert_eq!(cache.stats().entries, 2);
    }
    #[test]
    fn disabled_and_oversized_entries_are_never_retained() {
        let disabled = ResponseCache::new(0, Duration::from_secs(300));
        assert!(!disabled.insert(key(1), Arc::from(&b"{}"[..])));
        let cache = ResponseCache::new(MAX_BYTES, Duration::from_secs(300));
        assert!(!cache.insert(key(1), Arc::from(vec![b' '; MAX_ENTRY_BYTES + 1])));
        assert_eq!(cache.stats().bytes, 0);
    }
    #[test]
    fn canonical_query_order_and_generation_are_part_of_identity() {
        let a = BTreeMap::from([
            ("end_date".into(), "2024-12-31".into()),
            ("start_date".into(), "2024-01-01".into()),
        ]);
        let b = BTreeMap::from([
            ("start_date".into(), "2024-01-01".into()),
            ("end_date".into(), "2024-12-31".into()),
        ]);
        assert_eq!(
            ResponseCache::key(1, "GET", "/dashboard/stats", &a, &Value::Null, "").unwrap(),
            ResponseCache::key(1, "GET", "/dashboard/stats", &b, &Value::Null, "").unwrap()
        );
        assert_ne!(key(1), key(2));
    }
    #[test]
    fn many_small_results_cannot_exceed_entry_bookkeeping_bound() {
        let cache = ResponseCache::new(MAX_BYTES, Duration::from_secs(300));
        for n in 0..1000 {
            cache.insert(key(n), Arc::from(&b"{}"[..]));
        }
        assert_eq!(cache.stats().entries, MAX_ENTRIES);
        assert_eq!(cache.stats().bytes, MAX_ENTRIES * 2);
    }
}
