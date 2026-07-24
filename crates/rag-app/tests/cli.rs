use std::process::Command;

#[test]
fn version_uses_temporary_binary_name() {
    let output = Command::new(env!("CARGO_BIN_EXE_rag-rs"))
        .arg("--version")
        .output()
        .expect("rag-rs runs");
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout), "rag-rs 0.1.0\n");
}

#[test]
fn non_loopback_start_is_rejected_before_bind() {
    let output = Command::new(env!("CARGO_BIN_EXE_rag-rs"))
        .args(["start", "--host", "192.168.1.10", "--port", "7891"])
        .output()
        .expect("rag-rs runs");
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("is not loopback"));
}

#[test]
fn clean_environment_help_exposes_r6_r8_commands_without_python() {
    let output = Command::new(env!("CARGO_BIN_EXE_rag-rs"))
        .env_clear()
        .arg("--help")
        .output()
        .expect("rag-rs runs in a clean environment");
    assert!(output.status.success());
    let help = String::from_utf8_lossy(&output.stdout);
    for command in ["search", "index", "tui", "service", "migration"] {
        assert!(help.contains(command), "missing {command} from help");
    }
}
