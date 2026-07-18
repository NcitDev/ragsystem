use std::{
    fs,
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

use anyhow::{bail, Context};
use serde::Serialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ServicePlatform {
    MacOs,
    Linux,
}

impl ServicePlatform {
    pub fn current() -> anyhow::Result<Self> {
        match std::env::consts::OS {
            "macos" => Ok(Self::MacOs),
            "linux" => Ok(Self::Linux),
            other => bail!("service supervision is unsupported on {other}"),
        }
    }
}

#[derive(Debug, Serialize)]
pub struct ServiceStatus {
    pub platform: ServicePlatform,
    pub descriptor: PathBuf,
    pub installed: bool,
    pub active: bool,
}

pub fn descriptor_path(platform: ServicePlatform, home: &Path) -> PathBuf {
    match platform {
        ServicePlatform::MacOs => home.join("Library/LaunchAgents/dev.ragsystem.rag-rs.plist"),
        ServicePlatform::Linux => home.join(".config/systemd/user/rag-rs.service"),
    }
}

pub fn render(platform: ServicePlatform, executable: &Path, host: &str, port: u16) -> String {
    let exe = escape(executable.to_string_lossy().as_ref());
    let host = escape(host);
    match platform {
        ServicePlatform::MacOs => format!(
            r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>dev.ragsystem.rag-rs</string>
<key>ProgramArguments</key><array><string>{exe}</string><string>start</string><string>--host</string><string>{host}</string><string>--port</string><string>{port}</string></array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
</dict></plist>
"#
        ),
        ServicePlatform::Linux => format!(
            "[Unit]\nDescription=Rust RAG daemon\nAfter=network.target\n\n[Service]\nExecStart={exe} start --host {host} --port {port}\nRestart=on-failure\nNoNewPrivileges=true\n\n[Install]\nWantedBy=default.target\n"
        ),
    }
}

pub fn install(
    platform: ServicePlatform,
    home: &Path,
    executable: &Path,
    host: &str,
    port: u16,
) -> anyhow::Result<PathBuf> {
    // Cutover hygiene: the legacy Python launchd agent (`com.rag.daemon`,
    // KeepAlive=true) would keep restarting the old daemon on the same port.
    // Boot it out and remove its plist before installing ours (best-effort).
    if platform == ServicePlatform::MacOs {
        let legacy = home.join("Library/LaunchAgents/com.rag.daemon.plist");
        if legacy.exists() {
            if let Ok(uid) = user_id() {
                let _ = Command::new("launchctl")
                    .args(["bootout", &format!("gui/{uid}")])
                    .arg(&legacy)
                    .status();
            }
            let _ = fs::remove_file(&legacy);
        }
    }
    let destination = descriptor_path(platform, home);
    let parent = destination
        .parent()
        .context("service descriptor has no parent")?;
    fs::create_dir_all(parent)?;
    let temp = destination.with_extension("tmp");
    fs::write(&temp, render(platform, executable, host, port))?;
    fs::rename(&temp, &destination)?;
    Ok(destination)
}

pub fn uninstall(platform: ServicePlatform, home: &Path) -> anyhow::Result<bool> {
    let path = descriptor_path(platform, home);
    if !path.exists() {
        return Ok(false);
    }
    fs::remove_file(path)?;
    Ok(true)
}

pub fn activate(platform: ServicePlatform, descriptor: &Path) -> anyhow::Result<()> {
    let status = match platform {
        ServicePlatform::MacOs => Command::new("launchctl")
            .args(["bootstrap", &format!("gui/{}", user_id()?)])
            .arg(descriptor)
            .status(),
        ServicePlatform::Linux => Command::new("systemctl")
            .args(["--user", "enable", "--now", "rag-rs.service"])
            .status(),
    }
    .context("failed to invoke service supervisor")?;
    if !status.success() {
        bail!("service supervisor activation failed with {status}");
    }
    Ok(())
}

pub fn deactivate(platform: ServicePlatform) -> anyhow::Result<()> {
    let status = match platform {
        ServicePlatform::MacOs => Command::new("launchctl")
            .args([
                "bootout",
                &format!("gui/{}/dev.ragsystem.rag-rs", user_id()?),
            ])
            .status(),
        ServicePlatform::Linux => Command::new("systemctl")
            .args(["--user", "disable", "--now", "rag-rs.service"])
            .status(),
    }
    .context("failed to invoke service supervisor")?;
    if !status.success() {
        bail!("service supervisor deactivation failed with {status}");
    }
    Ok(())
}

pub fn status(platform: ServicePlatform, home: &Path) -> ServiceStatus {
    let descriptor = descriptor_path(platform, home);
    let installed = descriptor.exists();
    ServiceStatus {
        platform,
        installed,
        active: installed && is_active(platform),
        descriptor,
    }
}

fn is_active(platform: ServicePlatform) -> bool {
    let result = match platform {
        ServicePlatform::MacOs => user_id().ok().and_then(|uid| {
            Command::new("launchctl")
                .args(["print", &format!("gui/{uid}/dev.ragsystem.rag-rs")])
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status()
                .ok()
        }),
        ServicePlatform::Linux => Command::new("systemctl")
            .args(["--user", "is-active", "--quiet", "rag-rs.service"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .ok(),
    };
    result.is_some_and(|status| status.success())
}

fn user_id() -> anyhow::Result<String> {
    let output = Command::new("id").arg("-u").output()?;
    if !output.status.success() {
        bail!("failed to resolve user id");
    }
    Ok(String::from_utf8(output.stdout)?.trim().to_owned())
}

fn escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

#[cfg(test)]
mod tests {
    use tempfile::tempdir;

    use super::{install, status, uninstall, ServicePlatform};

    #[test]
    fn service_descriptors_install_and_remove_without_system_mutation() {
        let temp = tempdir().unwrap();
        let path = install(
            ServicePlatform::MacOs,
            temp.path(),
            std::path::Path::new("/tmp/rag-rs"),
            "127.0.0.1",
            7891,
        )
        .unwrap();
        assert!(path.exists());
        assert!(status(ServicePlatform::MacOs, temp.path()).installed);
        assert!(uninstall(ServicePlatform::MacOs, temp.path()).unwrap());
        assert!(!path.exists());
    }
}
