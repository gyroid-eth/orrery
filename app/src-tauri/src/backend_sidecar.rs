use std::{io, process::Command, sync::mpsc, thread};

pub(super) fn spawn(mut command: Command) -> io::Result<u32> {
    let (started, result) = mpsc::channel();
    // Start the waiter first so a thread-creation failure cannot strand a child.
    thread::Builder::new()
        .name("orrery-backend-wait".into())
        .spawn(move || match command.spawn() {
            Ok(mut child) => {
                let pid = child.id();
                let _ = started.send(Ok(pid));
                if let Err(error) = child.wait() {
                    eprintln!("ORRERY backend sidecar: could not reap pid {pid}: {error}");
                }
            }
            Err(error) => {
                let _ = started.send(Err(error));
            }
        })?;
    result.recv().map_err(io::Error::other)?
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::{
        io::Write,
        os::{fd::OwnedFd, unix::net::UnixStream},
        process::Stdio,
        time::{Duration, Instant},
    };

    #[test]
    fn reaps_sidecars_after_success_and_failure() {
        for status in [b"0\n".as_slice(), b"23\n".as_slice()] {
            let (mut input, stdin) = UnixStream::pair().unwrap();
            let mut command = Command::new("/bin/sh");
            command
                .args(["-c", "read -r status; exit \"$status\""])
                .stdin(Stdio::from(OwnedFd::from(stdin)));
            let (started, result) = mpsc::channel();
            thread::spawn(move || {
                let _ = started.send(spawn(command));
            });
            let pid = result
                .recv_timeout(Duration::from_secs(5))
                .unwrap()
                .unwrap()
                .to_string();
            input.write_all(status).unwrap();
            drop(input);

            let deadline = Instant::now() + Duration::from_secs(5);
            loop {
                let result = Command::new("/bin/ps")
                    .args(["-p", &pid, "-o", "state="])
                    .output()
                    .unwrap();
                if !result.status.success() {
                    break;
                }
                assert!(
                    Instant::now() < deadline,
                    "sidecar {pid} remained in state {}",
                    String::from_utf8_lossy(&result.stdout).trim()
                );
                thread::sleep(Duration::from_millis(25));
            }
        }
    }

    #[test]
    fn reports_spawn_errors() {
        let error = spawn(Command::new("/dev/null/orrery-sidecar")).unwrap_err();
        assert!(error.raw_os_error().is_some());
    }
}
