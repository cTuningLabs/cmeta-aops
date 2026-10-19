# Elasticsearch

Detect an existing installation or install the official full release archive, with its bundled JDK,
libraries, modules and configuration, into the current user's tool cache. The archive is checked against
Elastic's SHA-512 file. Setup does not start a server, install a system service or change application data.
The default version is declared in `_desc.yaml`; an explicit version overrides it.

```sh
cx tool setup elasticsearch
cx tool setup elasticsearch --detect
cx tool setup elasticsearch --version=7.17.29
cx tool setup elasticsearch --versions
cx tool setup elasticsearch --latest
cx tool run elasticsearch -- --version
cx tool check-updates elasticsearch
```

`--tool_path=<launcher>` detects a specific existing installation. Standard setup caching/version
selection applies; use a named cache when deliberately keeping several versions. The result exposes
`features.paths.home` for a distribution laid out with `bin/` below its root.

Linux x86_64/aarch64 and Windows x86_64 use upstream archives. Historical macOS availability depends on
the requested release; recent versions require Linux or Windows. There is no Windows ARM64 archive in
this installer. A missing release asset is an error, not a substitution of another version.

Windows archives retain the vendor scripts, and provide `cmeta-elasticsearch.cmd` as cMeta's launcher.
It calls the upstream Java launchers through the Python that installed the tool, so `!` in a cache path
does not undergo cmd delayed expansion. It honors `ES_JAVA_HOME`, `ES_PATH_CONF`, `CLI_JAVA_OPTS` and the
upstream Java launchers' `ES_JAVA_OPTS`. For a protected keystore supply `KEYSTORE_PASSWORD`. Standalone
server configuration, security, persistent data paths and supervision belong to the consuming task.

The full default distribution is large; `_desc_sizes.yaml` supplies setup's disk-space estimate.
Software in the downloaded distribution is under Elastic's own licenses, independent of cMeta's license.

Upstream: [downloads](https://www.elastic.co/downloads/elasticsearch),
[archive install](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/install-elasticsearch-from-archive-on-linux-macos),
[source/releases](https://github.com/elastic/elasticsearch).
