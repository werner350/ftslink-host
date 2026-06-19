# FTS Link Host

The native helper for [ftslink.com](https://ftslink.com). Someone runs this on
the computer they want help with; it shows a 6-character code; the helper enters
that code at ftslink.com and can then see and control the machine.

This repo exists to **build the downloadable apps automatically**. You don't
build anything on your own computer — GitHub does it in the cloud.

## How to get the apps

1. Push this repo to GitHub (see below). The **Build FTS Link Host** workflow
   runs automatically.
2. Open the **Actions** tab → the latest run → scroll to **Artifacts**.
3. Download:
   - **FTS-Link-Host-macos-latest** → Mac app for Apple Silicon (M1/M2/M3)
   - **FTS-Link-Host-macos-13** → Mac app for Intel Macs
   - **FTS-Link-Host-Windows** → `FTS Link Host.exe` for Windows
4. Send the matching file to the person you're helping. They unzip (Mac) and
   double-click. Nothing else to install.

## First-run notes for recipients

- **macOS:** unsigned, so the first time they must **right-click → Open →
  Open**. macOS will also ask to allow **Screen Recording** and **Accessibility**
  (System Settings → Privacy & Security) — both are required for sharing and
  control.
- **Windows:** SmartScreen may say "Windows protected your PC" → **More info →
  Run anyway**.

These one-time prompts go away only with paid code signing (Apple Developer
$99/yr; a Windows cert ~$100–200/yr).

## Pushing to GitHub

Create a new repository, then upload these files (including the `.github`
folder). The build starts on its own. You can also trigger it any time from the
Actions tab via **Run workflow**.
