# Building Signal-Android on Ubuntu (for LSP / serena)

Why: LSP-based tools (serena, jdtls, kotlin-language-server) need a project with a
**resolved classpath + generated sources**, which only exist after a Gradle build.
A bare `git clone` (what we RAG-index) is not enough for serena to resolve symbols.

Verified on the RTX-3080 box (`nikita@192.168.3.49`, Ubuntu) for commit
`d6871f8` (v8.15.3). Every step below is a gotcha we actually hit.

## Prerequisites

- **JDK 17** (NOT 21 — the default shell java on the box is 21, which Signal's build rejects)
  ```bash
  ls /usr/lib/jvm/java-17-openjdk-amd64        # confirm it exists
  export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
  ```
- **Android SDK** at `~/Android` (already installed), declared in `local.properties`:
  ```
  sdk.dir=/home/nikita/Android
  ```
- ~10 GB free disk (Gradle caches + build outputs), 8 GB+ RAM.

## Gotchas (all required)

1. **The app module is `:Signal-Android`, NOT `:app`.** `settings.gradle.kts` does
   `project(":app").name = "Signal-Android"`. So the task is
   `:Signal-Android:compilePlayProdDebugSources`, not `:app:...`.
2. **Use `--no-configuration-cache`.** Kotlin's `KotlinCompile` classpath-snapshot
   can't be serialized into Gradle's config cache → `BUILD FAILED ... serialization error`.
3. **Flavor is `playProdDebug`** (dimensions: distribution=`play`, environment=`prod`).
   The source-compile task resolves the classpath without packaging an APK.

## ⚠️ The real blocker: IPv6

Signal's own library `org.signal:libsignal-client` is served **only** from
`build-artifacts.signal.org`, which is **IPv6-only**. The box has **no IPv6 route**
→ `Could not GET ... Network is unreachable`. It is **not** on Maven Central (404).
You must resolve this one of three ways:

### Option A — Give the box IPv6 (best if your network supports it)
- If the router/ISP provides IPv6, enable it on the interface (netplan) and confirm:
  ```bash
  curl -6 -sI https://build-artifacts.signal.org/ | head -1   # want HTTP/2 200/403, not a hang
  ```
- If no native IPv6: use a tunnel (WireGuard to an IPv6-capable VPS, or Hurricane
  Electric `tunnelbroker.net`) or a NAT64/DNS64 gateway, then re-test the curl above.

### Option B — Pre-fetch libsignal on an IPv6 machine, copy the cache (no box IPv6 needed)
On a machine WITH IPv6 (e.g. the Mac), do a full successful build so the artifacts
land in the Gradle cache, then copy them over and build `--offline`:
```bash
# on the IPv6 machine, after a successful build:
rsync -a ~/.gradle/caches/modules-2/files-2.1/org.signal/ \
  nikita@192.168.3.49:~/.gradle/caches/modules-2/files-2.1/org.signal/
# on the box:
... ./gradlew :Signal-Android:compilePlayProdDebugSources --no-configuration-cache --offline
```
(Note: a *partial* Mac build may not have cached libsignal — verify with
`find ~/.gradle/caches -path '*libsignal-client*' -name '*.jar'` before copying.)

### Option C — Build libsignal from source (fully self-contained, needs Rust)
```bash
git clone https://github.com/signalapp/libsignal ~/development/libsignal   # IPv4 OK (github)
# install Rust toolchain if missing:  curl https://sh.rustup.rs -sSf | sh
# point Signal at the local build (uncomment in gradle.properties):
echo 'libsignalClientPath=../libsignal' >> ~/development/Signal-Android/gradle.properties
```
Then build (it compiles the Rust client too — slow first time).

## The build command (once IPv6/libsignal is resolved)

```bash
cd ~/development/Signal-Android
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
  ./gradlew :Signal-Android:compilePlayProdDebugSources \
  --no-configuration-cache --console=plain
```
First run downloads several GB and takes ~10–30 min. Success markers:
```
BUILD SUCCESSFUL
app/build/   now populated (generated sources: R.java, etc.)
```

## Verify the build is LSP-ready
```bash
ls -d app/build app/build/generated   # must exist and be non-empty
du -sh build app/build                # tens–hundreds of MB
```
Once `app/build/` exists with generated sources, serena's LSP can resolve symbols
(see build-serena-ubuntu.md).
