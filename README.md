<div align="center">
  <img src="assets/luffy.jpg" width="280" alt="Monkey D. Luffy wearing his straw hat">
  <h1>Ftorrent</h1>
  <p>A Windows terminal torrent downloader powered by Python and libtorrent.</p>
  <p>
    <img src="https://img.shields.io/badge/Platform-Windows-0078D4?style=for-the-badge" alt="Platform: Windows">
    <img src="https://img.shields.io/badge/Language-Python-FFD43B?style=for-the-badge&amp;logo=python&amp;logoColor=1C1C1C" alt="Language: Python">
    <img src="https://img.shields.io/badge/Engine-libtorrent-14B8A6?style=for-the-badge" alt="Engine: libtorrent">
    <img src="https://img.shields.io/badge/License-MIT-A855F7?style=for-the-badge" alt="License: MIT">
  </p>
</div>

---

## Features

- Open `.torrent` files or paste magnet links.
- Select individual files, whole folders, or `[0] All`.
- Track progress, download speed, and peers in a live terminal panel.
- Resume downloads from saved checkpoints.

## Quick start

Run these commands in PowerShell from the project folder.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "libtorrent>=2.1,<3"
.\.venv\Scripts\python.exe torrent_downloader.py
```

Choose **Upload File** or **Magnet Link**, then **Start Download**. Files are saved to `%USERPROFILE%\Downloads\Torrents`.

## 🤝 Contributing

Fork the repository, make a focused change, and run the relevant tests. Open a pull request with a brief description and screenshots for terminal changes. For bugs, include your Windows and Python versions and steps to reproduce.

## 📄 License

This project is licensed under the [MIT License](https://opensource.org/license/mit) — feel free to use, modify, and distribute it freely..
