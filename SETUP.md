# Setup

The supported installation path is Windows 11. Follow [SETUP-WINDOWS.md](SETUP-WINDOWS.md).

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

The installer stores the model credential with current-user Windows DPAPI, installs the Native Messaging host and registers the local flows. It does not install or trust a PATH-resolved extractor.

macOS/Linux scripts remain development utilities and are not in the current supported or commercial-pilot matrix.
