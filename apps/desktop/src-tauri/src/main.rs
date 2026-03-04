// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(not(test))]
fn main() {
    desktop_lib::run()
}

#[cfg(test)]
fn main() {}

#[cfg(test)]
mod tests {
    #[test]
    fn main_is_noop_under_tests() {
        super::main();
    }
}