# Brand assets

The official ORYN logo has not been supplied yet, so the app shows a plain placeholder mark and a
text wordmark. To use the real logo, save it as:

    frontend/src/assets/brand/logo.svg

(It lives under `src/assets` rather than `public/` so the build can detect at compile time whether
the file exists; a missing file under `public/` would be answered by the SPA fallback with HTML.)
The `Logo` component picks it up automatically on the next dev-server restart or build.
