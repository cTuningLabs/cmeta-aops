# OpenSearch

Detect an existing installation or install the official OpenSearch archive with bundled Java, libraries,
plugins and configuration. Setup verifies the upstream SHA-512 and retains the entire distribution in
the current user's tool cache. It does not start a server, configure demo security, create a password,
install a service or modify the firewall. The default version is declared in `_desc.yaml`.

```sh
cx tool setup opensearch
cx tool setup opensearch --detect
cx tool setup opensearch --version=3.9.0
cx tool setup opensearch --versions
cx tool setup opensearch --latest
cx tool run opensearch -- --version
cx tool check-updates opensearch
```

`--tool_path=<launcher>` detects a particular installation. Normal setup caching and explicit version
selection apply. `features.paths.home` identifies an archive distribution's root. Supported archives are
Linux x64/arm64 and Windows x64; use a Linux environment such as WSL/Docker on other systems.

Windows installs add `cmeta-opensearch.cmd`, which invokes the upstream JVM-options parser and Java
bootstrap through the installing Python. This avoids cmd delayed-expansion corruption of paths containing
`!`. It honors `OPENSEARCH_JAVA_HOME` (then `JAVA_HOME`, else bundled Java), `OPENSEARCH_PATH_CONF`,
`OPENSEARCH_JAVA_OPTS` and `OPENSEARCH_TMPDIR`. Protected keystores require `KEYSTORE_PASSWORD`.
Specialized FIPS/demo security setup should follow upstream's own configuration workflow.

Configure security, persistent data/log paths and supervision in the consuming task before starting a
node. `cx tool run opensearch -- --version` only prints the software version. See `_desc_sizes.yaml` for
the complete archive/extraction disk estimate. OpenSearch is Apache-2.0; client/API compatibility with
a particular Elasticsearch version must be assessed by the consuming application.

Upstream: [downloads](https://opensearch.org/downloads/),
[Windows install](https://docs.opensearch.org/latest/install-and-configure/install-opensearch/windows/),
[project and license](https://opensearch.org/about/),
[source/releases](https://github.com/opensearch-project/OpenSearch).
