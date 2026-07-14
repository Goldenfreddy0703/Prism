# Prism

[![Kodi version](https://img.shields.io/badge/Kodi%2020%2B%2F21%2F22-blue?style=for-the-badge)](https://kodi.tv/)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL3-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/GPL-3.0)
[![GitHub Wiki](https://img.shields.io/badge/docs-wiki-blue?style=for-the-badge)](https://github.com/Goldenfreddy0703/Prism/wiki)

**Prism** is an all-in-one Kodi addon for **Movies**, **TV Shows**, and **Anime** — built from a fork of the original [Seren](https://github.com/nixgates/plugin.video.seren) addon by **Nixgates**.

Browse, discover, track, and stream from a single menu. Prism is tightly integrated with [Simkl](https://simkl.com/) for watchlists, progress, and library sync. Playback is flexible — use **local files**, optional **debrid services**, or install **provider packages** for adaptive and embedded sources from streaming sites.

> **Credit where it's due:** All original Seren work belongs to [Nixgates](https://github.com/nixgates). Prism is a community-maintained fork built to keep the project alive and expand it with new features like anime support.

---

## Features

- **All-in-one media hub** — Movies, TV Shows, and Anime from one addon
- **Discover Anime** — Dedicated anime browsing with TV and movie categories, plus unified anime search
- **Simkl integration** — Sync watchlists, progress, ratings, Next Up, and personal libraries
- **Local file playback** — Browse and play media from folders on your device or network
- **Debrid support** *(optional)* — Real-Debrid, Premiumize, AllDebrid, and TorBox
- **Modular providers** — Install and manage provider packages from within the addon, including adaptive and embedded sources from streaming websites
- **Smart Play & filtering** — Source sorting, quality filters, adaptive playback, and more
- **Kodi 20–22** — Tested on Nexus, Omega, and Pulsar

For setup guides, provider configuration, and troubleshooting, see the **[Prism Wiki](https://github.com/Goldenfreddy0703/Prism/wiki)**.

---

## Requirements

- **Kodi 20 Nexus or later** (Kodi 19 and earlier are not supported)
- A **Simkl account** (recommended) for full library and sync features

### Playback options

Prism does **not** require a debrid account. How you play content is up to you:

- **Local files** — Point Prism at a folder on your device or network and play from your own library
- **Debrid services** *(recommended)* — Real-Debrid, Premiumize, AllDebrid, or TorBox for cached torrent and cloud playback
- **Provider packages** — Install adaptive or embedded providers to scrape streaming websites directly, if you choose to use them

---

## Installation

The recommended way to install Prism is through the **Prism Repository**, which enables automatic updates.

| Resource | URL |
|----------|-----|
| **Repository source** | `https://goldenfreddy0703.github.io/repository.prism` |
| **Repository repo** | [github.com/Goldenfreddy0703/repository.prism](https://github.com/Goldenfreddy0703/repository.prism) |
| **Addon source** | [github.com/Goldenfreddy0703/Prism](https://github.com/Goldenfreddy0703/Prism) |

> **Note:** The Prism Repository is being finalized for release. Once live, add the source URL above in Kodi's File Manager to install and receive updates automatically.

### Install via Repository (Recommended)

1. In Kodi, go to **Settings → File Manager → Add source**
2. Enter this URL as the source:
   ```
   https://goldenfreddy0703.github.io/repository.prism
   ```
3. Name it something like `Prism` and confirm
4. Go to **Add-ons → Install from zip file**, select your new source, and install `repository.prism`
5. Go to **Add-ons → Install from repository → Prism Repository** and install:
   - **Context Prism** (required dependency)
   - **Prism**

After installation, open Prism settings to set up playback — local folders, debrid accounts, provider packages, and Simkl. See the [Wiki](https://github.com/Goldenfreddy0703/Prism/wiki) for a full walkthrough.

### Manual Installation

Only use this if the repository is not yet available. Future updates should always come from the repository.

1. Install dependencies **in this order**:
   - Context Menu Addon (`context.prism`)
   - Prism Addon (`plugin.video.prism`)
2. After each update, **clear cache and rebuild the database** so changes take effect properly

Pre-built zip packages will be hosted in [repository.prism](https://github.com/Goldenfreddy0703/repository.prism) once the repository is published.

---

## Troubleshooting

Run into issues? Start here:

- **[Prism Wiki](https://github.com/Goldenfreddy0703/Prism/wiki)** — Setup, configuration, and common fixes
- **[GitHub Issues](https://github.com/Goldenfreddy0703/Prism/issues)** — Bug reports and troubleshooting
- **Addons4Kodi Discord** — Community support (link below)

---

## Contributing

Prism is a **community-driven** project. Seren was originally created by Nixgates, and this fork is maintained by volunteers who want to keep it going and improve it.

Contributions are welcome:

- **Bug reports & feature requests** — Open an [issue](https://github.com/Goldenfreddy0703/Prism/issues)
- **Code contributions** — Submit a pull request
- **Community support** — Help others in issues or on Discord

If you'd like to take an active role in development, reach out via the contact methods below — contributors who stick around may receive write access to the repo.

### Planned Features

- EasyNews debrid provider
- OffCloud debrid provider

---

## Contact

- **Discord:** The Steampunk Owl#3126
- **Keybase:** [Goldenfreddy0703](https://keybase.io/goldenfreddy0703)
- **Bug Reports:** [GitHub Issues](https://github.com/Goldenfreddy0703/Prism/issues)
- **Community Support:** [Addons4Kodi Discord](https://discord.gg/SqX7buB)

---

## Disclaimer

Prism is and always will be **free and open-source**. None of its code or resources may be sold or redistributed for commercial purposes.

This addon and its developers **do not** host, create, or distribute any of the content displayed in the addon. It scrapes publicly available websites. Users are responsible for complying with all applicable laws and regulations in their country.

Prism and its developers are not affiliated with Team Kodi, Simkl, or any of the sites and providers used in the addon.

---

## License

Prism is licensed under the **[GPL-3.0 License](https://opensource.org/licenses/GPL-3.0)**.
