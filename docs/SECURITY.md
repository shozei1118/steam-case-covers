# Security

Case Covers runs on your computer. It retrieves artwork from Steam and optionally SteamGridDB. SteamGridDB uses a personal API key stored in the OS credential store; it is never saved in plaintext or logged. Local artwork export needs no Steam login or API key. The app does not upload your local artwork and does not require elevated rights.

If you find a security problem, please report it privately: open the **Security** tab of this repository and choose **Report a vulnerability**. Please don't post details in a public issue first.

Automated release files are built by GitHub Actions from the tagged source. The v1.5.2 Windows installer was built and tested locally, then uploaded unchanged. Each release lists SHA-256 checksums in `SHA256SUMS`, so you can verify what you downloaded.

Automated builds from this public repository can carry signed build provenance (the manually uploaded v1.5.2 installer has no GitHub build attestation): a certificate, signed by GitHub, saying which commit of this repository built that exact file. To check a download (needs the GitHub CLI):

```bash
gh attestation verify CaseCovers-linux --repo shozei1118/steam-case-covers
```
