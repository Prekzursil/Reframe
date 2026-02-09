use std::path::PathBuf;
use std::process::Command;

fn find_compose_file() -> Result<PathBuf, String> {
    let mut current = std::env::current_dir().map_err(|e| format!("Unable to read current dir: {e}"))?;
    loop {
        let candidate = current.join("infra").join("docker-compose.yml");
        if candidate.is_file() {
            return Ok(candidate);
        }
        if !current.pop() {
            break;
        }
    }
    Err("Could not locate infra/docker-compose.yml; run the desktop app from inside the repo checkout.".to_string())
}

fn format_output(stdout: &[u8], stderr: &[u8]) -> String {
    let mut out = String::new();
    if !stdout.is_empty() {
        out.push_str(&String::from_utf8_lossy(stdout));
    }
    if !stderr.is_empty() {
        if !out.ends_with('\n') && !out.is_empty() {
            out.push('\n');
        }
        out.push_str(&String::from_utf8_lossy(stderr));
    }
    out.trim().to_string()
}

fn run_checked(mut cmd: Command) -> Result<String, String> {
    let output = cmd.output().map_err(|e| format!("Command failed to start: {e}"))?;
    let rendered = format_output(&output.stdout, &output.stderr);
    if output.status.success() {
        return Ok(rendered);
    }
    let code = output.status.code().map(|c| c.to_string()).unwrap_or_else(|| "unknown".to_string());
    Err(format!("Command failed (exit {code})\n{rendered}"))
}

fn docker_compose_unsupported(rendered: &str) -> bool {
    let s = rendered.to_lowercase();
    s.contains("is not a docker command")
        || s.contains("unknown command")
        || s.contains("unknown shorthand flag")
        || s.contains("unknown flag: --no-build")
}

fn run_compose(args: &[&str]) -> Result<String, String> {
    let compose_path = find_compose_file()?;
    let compose_dir = compose_path
        .parent()
        .ok_or_else(|| "Invalid compose file path".to_string())?;

    // Prefer `docker compose`, but fall back to the legacy `docker-compose` binary when necessary.
    let docker_result = run_checked({
        let mut cmd = Command::new("docker");
        cmd.current_dir(compose_dir)
            .arg("compose")
            .arg("-f")
            .arg(&compose_path)
            .args(args);
        cmd
    });

    match docker_result {
        Ok(out) => Ok(out),
        Err(err) => {
            // If docker isn't installed, `run_checked` would have failed to start; in that case
            // try `docker-compose` before returning the error.
            let is_not_found = err.to_lowercase().contains("failed to start");
            if is_not_found || docker_compose_unsupported(&err) {
                run_checked({
                    let mut cmd = Command::new("docker-compose");
                    cmd.current_dir(compose_dir).arg("-f").arg(&compose_path).args(args);
                    cmd
                })
            } else {
                Err(err)
            }
        }
    }
}

#[tauri::command]
fn docker_version() -> Result<String, String> {
    let mut cmd = Command::new("docker");
    cmd.arg("--version");
    run_checked(cmd)
}

#[tauri::command]
fn compose_file_path() -> Result<String, String> {
    Ok(find_compose_file()?.display().to_string())
}

#[tauri::command]
fn compose_ps() -> Result<String, String> {
    run_compose(&["ps"])
}

#[tauri::command]
fn compose_up(build: Option<bool>) -> Result<String, String> {
    let mut args = vec!["up", "-d", "--remove-orphans"];
    if build.unwrap_or(true) {
        args.push("--build");
    } else {
        args.push("--no-build");
    }
    run_compose(&args)
}

#[tauri::command]
fn compose_down() -> Result<String, String> {
    run_compose(&["down"])
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_process::init())
        .setup(|app| {
            #[cfg(desktop)]
            app.handle()
                .plugin(tauri_plugin_updater::Builder::new().build())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            docker_version,
            compose_file_path,
            compose_ps,
            compose_up,
            compose_down
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
