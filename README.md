<p align="center">
  <img src="https://img.shields.io/badge/Streamload-v0.1.1-blue?style=for-the-badge" alt="Version"/>
  <img src="https://img.shields.io/badge/python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=for-the-badge" alt="Platform"/>
  <img src="https://img.shields.io/badge/license-AGPL--3.0-green?style=for-the-badge" alt="License"/>
</p>

<h1 align="center">Streamload</h1>

<p align="center">
  <strong>A powerful CLI tool for downloading video content from Italian streaming services.</strong>
</p>

<p align="center">
  Interactive &bull; Multi-service &bull; Fast &bull; Configurable
</p>

---

## About

Streamload is an interactive command-line video downloader that aggregates search results across 15 streaming platforms. It provides a clean, keyboard-driven interface for browsing, selecting, and downloading video content with full control over audio tracks, subtitles, and output quality.

## Features

- **Interactive CLI** -- Rich terminal interface with colors, tables, spinners, and progress bars
- **Multi-service search** -- Search across all 15 supported services simultaneously with parallel requests
- **Track selection** -- Choose specific audio languages and subtitle tracks before downloading
- **Quality control** -- Automatic 1080p targeting with graceful fallback
- **Multi-threaded downloads** -- Concurrent segment downloading for maximum speed
- **Customizable output** -- Configurable folder structure, naming patterns, and file formats
- **Internationalization** -- Full English and Italian interface support
- **Auto-update** -- Built-in update checker to stay on the latest version
- **DRM support** -- Widevine and PlayReady decryption via remote CDM
- **Batch downloads** -- Queue multiple episodes or films for sequential download

## Supported Services

| Service | Category | Language |
|:--------|:---------|:---------|
| AnimeUnity | Anime | IT |
| AnimeWorld | Anime | IT |
| Crunchyroll | Anime | Multi |
| Discovery+ | Film / Serie | IT |
| DMAX | Serie | IT |
| Food Network | Serie | IT |
| GuardaSerie | Serie | IT |
| HomeGardenTV | Serie | IT |
| Mediaset Infinity | Film / Serie | IT |
| MostraGuarda | Film | IT |
| Nove | Serie | IT |
| RaiPlay | Film / Serie | IT |
| Real Time | Serie | IT |
| StreamingCommunity | Film / Serie | IT |
| TubiTV | Serie | EN |

## Domain Rotation

Italian streaming sites rotate domains frequently. Streamload tracks them automatically so you rarely need to intervene.

- The active domain list is stored in `domains.json` in this repository, signed with Ed25519. When GitHub raw is unreachable, a jsDelivr CDN mirror serves the same signed bytes as a fallback.
- Every candidate domain is actively probed before use: parking pages, ISP hijack pages, and connection errors are all rejected silently.
- The resolved domain is cached for 6 hours. On the next startup after the TTL expires, Streamload re-resolves in the background.
- For an emergency override, set `services.<short_name>.base_url` in `config.json` -- the config source is always consulted first, bypassing the network entirely.
- Manage resolution state from the command line:

      python streamload-domains.py status    # show current cache state
      python streamload-domains.py refresh   # force re-resolution for all services
      python streamload-domains.py pin <service> <url>  # pin a URL for one service

For full operator instructions, including how to update `domains.json` and rotate the signing key, see [`docs/domain-resolver.md`](docs/domain-resolver.md).

## Requirements

- **Python 3.10** or higher
- **FFmpeg** -- automatically installed via the `imageio-ffmpeg` dependency

## Installation

**1. Clone the repository**

    git clone https://github.com/alfanowski/Streamload.git
    cd Streamload

**2. Install dependencies**

    pip install -r requirements.txt

**3. Run Streamload**

    python -m streamload

## Usage

Launch Streamload and follow the interactive prompts:

1. **Search** -- Enter the title of a film, series, or anime. Streamload searches all supported services in parallel and displays aggregated results.
2. **Select** -- Browse the results table and select your desired title. For series, navigate through available seasons and episodes.
3. **Configure tracks** -- Choose your preferred audio language and subtitle tracks from the available options.
4. **Download** -- Confirm your selection and Streamload handles the rest: fetching, decrypting, merging, and organizing the final file.

Downloaded files are saved to the configured output directory with automatic folder organization by content type.

## Configuration

Streamload uses a `config.json` file for customization. Copy the example to get started:

    cp config.json.example config.json

Configurable options include:

- **Output paths** -- Root directory, folder structure per content type, file naming patterns
- **Download settings** -- Thread count, retry attempts, concurrent downloads, speed limits
- **Processing** -- GPU acceleration, subtitle format, automatic audio/subtitle merging
- **Network** -- Timeout, retries, SSL verification, proxy support
- **DRM** -- Widevine and PlayReady remote CDM configuration
- **Interface** -- Language preference (English / Italian), preferred audio and subtitle languages

See [`config.json.example`](config.json.example) for the full reference.

## Keyboard Shortcuts

| Key | Action |
|:----|:-------|
| `Arrow Keys` | Navigate through lists and menus |
| `Enter` | Confirm selection |
| `Esc` | Go back / cancel |
| `Space` | Toggle selection (multi-select mode) |
| `Tab` | Switch between panels or options |
| `q` | Quit the application |

## Credits

**Author:** [alfanowski](https://github.com/alfanowski)

Built with the help of these open-source projects:

- [N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE) -- HLS/DASH stream downloader
- [FFmpeg](https://ffmpeg.org) -- Audio/video processing and muxing
- [Rich](https://github.com/Textualize/rich) -- Terminal UI framework
- [httpx](https://github.com/encode/httpx) -- Modern HTTP client

## Disclaimer

**This software is provided strictly for educational and personal use.**

By using Streamload, you acknowledge and agree to the following terms:

- **Compliance.** You are solely responsible for ensuring that your use of this tool complies with all applicable local, national, and international laws and regulations. The developer assumes no responsibility for verifying the legality of your actions.

- **Copyrighted content.** Downloading, reproducing, or distributing copyrighted material without explicit authorization from the rights holder may constitute a violation of copyright law. This tool does not encourage, endorse, or facilitate copyright infringement in any form.

- **No hosted content.** Streamload does not host, store, index, or distribute any media content. It functions solely as a client-side utility that interacts with publicly accessible streaming APIs.

- **No liability.** The developer of this software shall not be held liable for any direct, indirect, incidental, or consequential damages arising from the use or misuse of this tool. This includes, but is not limited to, legal consequences resulting from unauthorized downloading of protected content.

- **No warranty.** This software is provided "as is", without warranty of any kind, express or implied. The developer makes no guarantees regarding the functionality, reliability, or availability of any supported service.

- **Acceptance.** By downloading, installing, or using Streamload, you indicate your full acceptance of these terms. If you do not agree with any part of this disclaimer, you must immediately cease all use of the software and delete all copies in your possession.

**Use responsibly and respect content creators.**

## License

This project is licensed under the [GNU Affero General Public License v3.0](https://www.gnu.org/licenses/agpl-3.0.html).
