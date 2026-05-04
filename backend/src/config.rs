use std::env;
use std::net::{IpAddr, Ipv4Addr, SocketAddr};
use std::path::PathBuf;

#[derive(Debug, Clone)]
pub struct Config {
    pub database_url: String,
    pub bind_addr: SocketAddr,
    pub client_origin: String,
    pub reader_runtime_dir: PathBuf,
    pub reader_image_retention_days: u16,
}

impl Config {
    pub fn from_env() -> anyhow::Result<Self> {
        let database_url = env::var("DATABASE_URL")
            .unwrap_or_else(|_| "postgres://water-meter:water-meter@localhost:5432/water_meter".to_owned());
        let host = env::var("APP_HOST")
            .ok()
            .and_then(|value| value.parse::<IpAddr>().ok())
            .unwrap_or(IpAddr::V4(Ipv4Addr::UNSPECIFIED));
        let port = env::var("APP_PORT")
            .ok()
            .and_then(|value| value.parse::<u16>().ok())
            .unwrap_or(8080);
        let client_origin =
            env::var("CLIENT_ORIGIN").unwrap_or_else(|_| "http://localhost:5173".to_owned());
        let reader_runtime_dir = env::var("READER_RUNTIME_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("../reader/runtime"));
        let reader_image_retention_days = env::var("READER_IMAGE_RETENTION_DAYS")
            .ok()
            .and_then(|value| value.parse::<u16>().ok())
            .filter(|value| *value > 0)
            .unwrap_or(30);
        Ok(Self {
            database_url,
            bind_addr: SocketAddr::new(host, port),
            client_origin,
            reader_runtime_dir,
            reader_image_retention_days,
        })
    }
}
