use super::*;
use std::env;
use std::fs;
use std::path::Path;
use std::sync::{Mutex, MutexGuard, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

fn env_lock() -> MutexGuard<'static, ()> {
    static ENV_LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    match ENV_LOCK.get_or_init(|| Mutex::new(())).lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    }
}

fn unique_temp_dir(prefix: &str) -> PathBuf {
    let mut dir = if cfg!(target_os = "windows") {
        env::var_os("TEMP")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("C:/reframe-test-tmp"))
    } else {
        env::var_os("TMPDIR")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("/tmp/reframe-test-tmp"))
    };
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time went backwards")
        .as_nanos();
    dir.push("reframe-desktop-tests");
    dir.push(format!("{prefix}-{now}"));
    fs::create_dir_all(&dir).expect("failed to create temp dir");
    dir
}

fn write_file(path: &Path, content: &str) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("failed to create parent dir");
    }
    fs::write(path, content).expect("failed to write file");
}

#[test]
fn has_runtime_layout_checks_expected_tree() {
    let root = unique_temp_dir("reframe-runtime-layout");
    assert!(!has_runtime_layout(&root));

    write_file(&root.join("apps").join("api").join("app").join("main.py"), "pass\n");
    fs::create_dir_all(
        root.join("packages")
            .join("media-core")
            .join("src")
            .join("media_core"),
    )
    .expect("failed to create media_core dir");

    assert!(has_runtime_layout(&root));
    let _ = fs::remove_dir_all(root);
}

#[test]
fn format_output_combines_stdout_and_stderr() {
    let rendered = format_output(b"hello", b"warn");
    assert_eq!(rendered, "hello\nwarn");
    assert_eq!(format_output(b"", b""), "");
}

#[test]
fn candidate_python_binaries_honors_explicit_env() {
    let _env_guard = env_lock();
    let root = unique_temp_dir("reframe-python-candidates");
    env::set_var("REFRAME_DESKTOP_PYTHON", "custom-python");
    let candidates = candidate_python_binaries(&root);
    assert_eq!(candidates.first().and_then(|p| p.to_str()), Some("custom-python"));
    env::remove_var("REFRAME_DESKTOP_PYTHON");
    let _ = fs::remove_dir_all(root);
}

#[test]
fn pythonpath_for_runtime_contains_api_and_media_core_paths() {
    let root = unique_temp_dir("reframe-pythonpath");
    let joined = pythonpath_for_runtime(&root).expect("pythonpath assembly failed");
    let paths: Vec<PathBuf> = env::split_paths(&joined).collect();

    assert!(paths.contains(&root));
    assert!(paths.contains(&root.join("apps").join("api")));
    assert!(paths.contains(&root.join("packages").join("media-core").join("src")));
    let _ = fs::remove_dir_all(root);
}

#[test]
fn desktop_web_dist_detects_index_file() {
    let root = unique_temp_dir("reframe-web-dist");
    assert!(desktop_web_dist(&root).is_none());

    let dist = root.join("apps").join("web").join("dist");
    write_file(&dist.join("index.html"), "<html></html>");
    assert_eq!(desktop_web_dist(&root), Some(dist));
    let _ = fs::remove_dir_all(root);
}

#[test]
fn runtime_venv_helpers_resolve_expected_paths() {
    let _env_guard = env_lock();
    let root = unique_temp_dir("reframe-venv");
    env::set_var("REFRAME_DESKTOP_APP_DATA", root.join("data"));

    let data = desktop_data_dir(&root).expect("desktop data dir");
    assert!(data.is_dir());

    let venv = venv_dir(&root).expect("venv dir");
    let python = venv_python(&venv);
    let marker = venv.join(".reframe_runtime_ready");
    assert!(!runtime_venv_ready(&python, &marker));

    write_file(&python, "");
    write_file(&marker, "ready\n");
    assert!(runtime_venv_ready(&python, &marker));

    env::remove_var("REFRAME_DESKTOP_APP_DATA");
    let _ = fs::remove_dir_all(root);
}

#[test]
fn build_runtime_command_sets_local_queue_defaults() {
    let root = unique_temp_dir("reframe-runtime-cmd");
    let python = PathBuf::from("python");
    let py_path = pythonpath_for_runtime(&root).expect("pythonpath");
    let media_root = root.join("media");
    fs::create_dir_all(&media_root).expect("media root create");

    let cmd = build_runtime_command(&root, &python, py_path, &media_root);
    let args: Vec<String> = cmd
        .get_args()
        .map(|arg| arg.to_string_lossy().to_string())
        .collect();

    assert!(args.contains(&"--factory".to_string()));
    assert!(args.contains(&"app.main:create_app".to_string()));
    assert!(args.contains(&"--port".to_string()));
    assert!(args.contains(&"8000".to_string()));

    let envs: Vec<(String, String)> = cmd
        .get_envs()
        .filter_map(|(k, v)| Some((k.to_string_lossy().to_string(), v?.to_string_lossy().to_string())))
        .collect();

    let find = |key: &str| envs.iter().find(|(k, _)| k == key).map(|(_, v)| v.clone());
    assert_eq!(find("REFRAME_LOCAL_QUEUE_MODE"), Some("true".to_string()));
    assert_eq!(find("BROKER_URL"), Some("memory://".to_string()));
    assert_eq!(find("RESULT_BACKEND"), Some("cache+memory://".to_string()));
    assert_eq!(find("REFRAME_MEDIA_ROOT"), Some(media_root.to_string_lossy().to_string()));

    let _ = fs::remove_dir_all(root);
}

#[test]
fn local_runtime_status_reports_stopped_when_no_child() {
    let status = local_runtime_status().expect("local runtime status");
    assert!(status.contains("api stopped"));
    assert!(status.contains("queue mode: local"));
}

#[test]
fn runtime_root_from_env_rejects_invalid_layout() {
    let _env_guard = env_lock();
    let root = unique_temp_dir("reframe-runtime-root-env");
    env::set_var("REFRAME_DESKTOP_RUNTIME_ROOT", &root);
    assert!(runtime_root_from_env().is_none());

    write_file(&root.join("apps").join("api").join("app").join("main.py"), "pass\n");
    fs::create_dir_all(
        root.join("packages")
            .join("media-core")
            .join("src")
            .join("media_core"),
    )
    .expect("failed to create media_core dir");

    let resolved = runtime_root_from_env();
    assert_eq!(resolved, Some(root.clone()));
    env::remove_var("REFRAME_DESKTOP_RUNTIME_ROOT");
    let _ = fs::remove_dir_all(root);
}

#[test]
fn run_checked_handles_success_and_failure() {
    let ok = if cfg!(target_os = "windows") {
        let mut cmd = Command::new("cmd");
        cmd.args(["/C", "echo ok"]);
        cmd
    } else {
        let mut cmd = Command::new("sh");
        cmd.args(["-c", "echo ok"]);
        cmd
    };
    let output = run_checked(ok).expect("expected command success");
    assert!(output.contains("ok"));

    let bad = if cfg!(target_os = "windows") {
        let mut cmd = Command::new("cmd");
        cmd.args(["/C", "exit 7"]);
        cmd
    } else {
        let mut cmd = Command::new("sh");
        cmd.args(["-c", "exit 7"]);
        cmd
    };
    let err = run_checked(bad).expect_err("expected non-zero command to fail");
    assert!(err.contains("exit"));
}

#[test]
fn runtime_requirement_files_require_both_manifests() {
    let root = unique_temp_dir("reframe-runtime-reqs");
    let missing = runtime_requirement_files(&root).expect_err("missing requirements should fail");
    assert!(missing.contains("requirements.txt"));

    write_file(
        &root.join("apps").join("api").join("requirements.txt"),
        "fastapi==0.0\n",
    );
    let missing_worker = runtime_requirement_files(&root).expect_err("worker requirements should still be missing");
    assert!(missing_worker.contains("services"));

    write_file(
        &root.join("services").join("worker").join("requirements.txt"),
        "celery==0.0\n",
    );
    let both = runtime_requirement_files(&root).expect("both requirement files should be discovered");
    assert!(both.0.is_file());
    assert!(both.1.is_file());
    let _ = fs::remove_dir_all(root);
}

#[test]
fn ensure_media_root_uses_desktop_data_dir() {
    let _env_guard = env_lock();
    let root = unique_temp_dir("reframe-media-root");
    env::set_var("REFRAME_DESKTOP_APP_DATA", root.join("data"));
    let media = ensure_media_root(&root).expect("media root creation should succeed");
    assert!(media.is_dir());
    assert!(media.ends_with("media"));
    env::remove_var("REFRAME_DESKTOP_APP_DATA");
    let _ = fs::remove_dir_all(root);
}
#[test]
fn find_repo_root_detects_ancestor_layout() {
    let _env_guard = env_lock();
    let root = unique_temp_dir("reframe-find-root");
    write_file(&root.join("apps").join("api").join("app").join("main.py"), "pass\n");
    fs::create_dir_all(
        root.join("packages")
            .join("media-core")
            .join("src")
            .join("media_core"),
    )
    .expect("failed to create media_core dir");

    let nested = root.join("apps").join("api");
    fs::create_dir_all(&nested).expect("nested dir create");

    let previous = env::current_dir().expect("current dir");
    env::set_current_dir(&nested).expect("set current dir");
    let found = find_repo_root().expect("expected repo root from ancestor search");
    assert_eq!(found, root);
    env::set_current_dir(previous).expect("restore current dir");

    let _ = fs::remove_dir_all(found);
}

#[test]
fn find_runtime_root_prefers_explicit_env_layout() {
    let _env_guard = env_lock();
    let root = unique_temp_dir("reframe-runtime-env");
    write_file(&root.join("apps").join("api").join("app").join("main.py"), "pass\n");
    fs::create_dir_all(
        root.join("packages")
            .join("media-core")
            .join("src")
            .join("media_core"),
    )
    .expect("failed to create media_core dir");

    env::set_var("REFRAME_DESKTOP_RUNTIME_ROOT", &root);
    let found = find_runtime_root().expect("runtime root from env");
    assert_eq!(found, root);
    env::remove_var("REFRAME_DESKTOP_RUNTIME_ROOT");
    let _ = fs::remove_dir_all(found);
}

#[test]
fn mark_runtime_ready_writes_marker_file() {
    let root = unique_temp_dir("reframe-runtime-marker");
    let marker = root.join("ready.marker");
    mark_runtime_ready(&marker).expect("marker write should succeed");
    let payload = fs::read_to_string(&marker).expect("marker read");
    assert_eq!(payload.trim(), "ready");
    let _ = fs::remove_dir_all(root);
}

#[test]
fn create_runtime_venv_if_missing_respects_existing_python_binary() {
    let root = unique_temp_dir("reframe-existing-venv");
    let venv = root.join("venv");
    let python = venv.join(if cfg!(target_os = "windows") {
        "Scripts/python.exe"
    } else {
        "bin/python"
    });
    write_file(&python, "");

    let host = if cfg!(target_os = "windows") {
        PathBuf::from("cmd")
    } else {
        PathBuf::from("sh")
    };

    create_runtime_venv_if_missing(&host, &venv, &python).expect("existing python should short-circuit");
    assert!(python.is_file());
    let _ = fs::remove_dir_all(root);
}

#[test]
fn api_is_running_clears_finished_child_state() {
    let mut state = RuntimeState::default();
    let child = if cfg!(target_os = "windows") {
        let mut cmd = Command::new("cmd");
        cmd.args(["/C", "exit 0"]);
        cmd.spawn().expect("spawn child")
    } else {
        let mut cmd = Command::new("sh");
        cmd.args(["-c", "exit 0"]);
        cmd.spawn().expect("spawn child")
    };

    state.api = Some(child);

    std::thread::sleep(std::time::Duration::from_millis(50));
    let running = api_is_running(&mut state).expect("api_is_running should succeed");
    assert!(!running);
    assert!(state.api.is_none());
}

#[test]
fn api_is_running_reports_true_for_active_child() {
    let mut state = RuntimeState::default();
    let child = if cfg!(target_os = "windows") {
        let mut cmd = Command::new("cmd");
        cmd.args(["/C", "ping -n 3 127.0.0.1 >NUL"]);
        cmd.spawn().expect("spawn child")
    } else {
        let mut cmd = Command::new("sh");
        cmd.args(["-c", "sleep 1"]);
        cmd.spawn().expect("spawn child")
    };
    state.api = Some(child);

    let running = api_is_running(&mut state).expect("api_is_running should succeed");
    assert!(running);
    let _ = stop_local_runtime();
}

#[test]
fn resolve_host_python_binary_handles_absolute_and_path_failure() {
    let _env_guard = env_lock();
    let root = unique_temp_dir("reframe-resolve-python");
    let explicit = root.join("python-explicit");
    write_file(&explicit, "placeholder");

    env::set_var("REFRAME_DESKTOP_PYTHON", &explicit);
    let resolved = resolve_host_python_binary(&root).expect("explicit absolute python path");
    assert_eq!(resolved, explicit);

    env::set_var("REFRAME_DESKTOP_PYTHON", root.join("missing-python"));
    let old_path = env::var("PATH").unwrap_or_default();
    env::set_var("PATH", "");
    let err = resolve_host_python_binary(&root).expect_err("missing python candidates should fail");
    assert!(err.contains("No usable Python runtime found"));
    env::set_var("PATH", old_path);
    env::remove_var("REFRAME_DESKTOP_PYTHON");
    let _ = fs::remove_dir_all(root);
}

#[test]
fn desktop_data_dir_falls_back_when_env_blank() {
    let _env_guard = env_lock();
    let root = unique_temp_dir("reframe-desktop-data-fallback");
    env::set_var("REFRAME_DESKTOP_APP_DATA", "   ");
    let data = desktop_data_dir(&root).expect("fallback desktop data dir");
    assert!(data.ends_with(".desktop-runtime"));
    assert!(data.is_dir());
    env::remove_var("REFRAME_DESKTOP_APP_DATA");
    let _ = fs::remove_dir_all(root);
}

#[test]
fn create_runtime_venv_if_missing_returns_spawn_error_for_missing_host_binary() {
    let root = unique_temp_dir("reframe-venv-missing-host");
    let venv = root.join("venv");
    let python = venv_python(&venv);
    let missing_host = root.join("missing-host-python");

    let err = create_runtime_venv_if_missing(&missing_host, &venv, &python)
        .expect_err("missing host python must fail");
    assert!(err.contains("Command failed to start"));
    let _ = fs::remove_dir_all(root);
}

#[test]
fn install_runtime_requirements_reports_command_failure() {
    let root = unique_temp_dir("reframe-install-runtime-req-fail");
    let missing_python = root.join("missing-python");
    let req_api = root.join("api-req.txt");
    let req_worker = root.join("worker-req.txt");
    write_file(&req_api, "fastapi\n");
    write_file(&req_worker, "celery\n");

    let err = install_runtime_requirements(&missing_python, &req_api, &req_worker)
        .expect_err("missing python binary should fail pip install");
    assert!(err.contains("Command failed to start"));
    let _ = fs::remove_dir_all(root);
}

#[test]
fn command_wrappers_fail_closed_when_runtime_root_missing() {
    let _env_guard = env_lock();
    let root = unique_temp_dir("reframe-command-wrapper-missing-root");
    let previous = env::current_dir().expect("current dir");
    env::set_current_dir(&root).expect("switch to isolated cwd");
    env::set_var("REFRAME_DESKTOP_RUNTIME_ROOT", root.join("missing-runtime"));

    let prep_err = runtime_prepare().expect_err("runtime_prepare must fail without runtime root");
    assert!(prep_err.contains("Could not locate runtime root"));

    let docker_err = docker_version().expect_err("docker_version wrapper must fail without runtime root");
    assert!(docker_err.contains("Could not locate runtime root"));

    let compose_path_err = compose_file_path().expect_err("compose_file_path must fail without runtime root");
    assert!(compose_path_err.contains("Could not locate runtime root"));

    let up_err = compose_up(Some(true)).expect_err("compose_up must fail without runtime root");
    assert!(up_err.contains("Could not locate runtime root"));

    let ps = compose_ps().expect("compose_ps fallback status");
    assert!(ps.contains("queue mode: local"));
    let down = compose_down().expect("compose_down fallback status");
    assert!(down.contains("not running"));

    env::remove_var("REFRAME_DESKTOP_RUNTIME_ROOT");
    env::set_current_dir(previous).expect("restore current dir");
    let _ = fs::remove_dir_all(root);
}

#[test]
fn stop_local_runtime_stops_active_child() {
    let mut guard = runtime_state_guard().expect("runtime lock");
    let child = if cfg!(target_os = "windows") {
        let mut cmd = Command::new("cmd");
        cmd.args(["/C", "ping -n 5 127.0.0.1 >NUL"]);
        cmd.spawn().expect("spawn active child")
    } else {
        let mut cmd = Command::new("sh");
        cmd.args(["-c", "sleep 5"]);
        cmd.spawn().expect("spawn active child")
    };
    guard.api = Some(child);
    drop(guard);

    let out = stop_local_runtime().expect("stop local runtime");
    assert!(out.contains("stopped"));
}
