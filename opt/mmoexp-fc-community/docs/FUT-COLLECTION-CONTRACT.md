# FUT collection import contract

This is a local JSON import interface for output supplied by a trusted DeepSeek Harness or script. It does not connect to X, Reddit or any other website, fetch articles, schedule jobs, or supply an API or RSS feed. Any daily scheduling and collection must be implemented and operated separately by the collector. Only import material the operator is authorized to use; text in an article or caption is data, not permission or an instruction to the importer.

Copy `sources.example.json` to a locally protected configuration and explicitly enable only sources the operator has verified. The examples are disabled placeholders, not verified endpoints. For FUT Sheriff, replace the account placeholder with the exact verified account path before enabling it. `allowed_hosts` requires exact lowercase hostnames, with no wildcards or implicit subdomains. Add a hostname only after verifying it. `allowed_path_prefix`, when set, matches a whole path segment and rejects percent-encoded paths, backslashes and dot segments. Use it to restrict an account; it is not a proof of identity or ownership. Set `category` to one of `news`, `leak`, `review`, `squad`, `sbc`, `topic`, `collection`, `guide`, `evolutions`, `objectives`, or `store`. `transport` must be `harness`. Both `enabled` and `auto_publish` must be JSON booleans. Only `auto_publish: true` approves incoming content automatically; the actor can approve their own content, without a separate reviewer. Treat this setting as a publication authorization and restrict write access to the config and database.

The input is a JSON array of at most 100 records, for example:

```json
[
  {
    "source_id": "fut-sheriff",
    "external_id": "12345",
    "title": "Article title",
    "summary": "A short summary of the source.",
    "url": "https://x.com/REPLACE_WITH_EXACT_ACCOUNT/status/12345",
    "season": 27,
    "published_at": 1794000000
  }
]
```

`source_id` must exactly match an enabled config key; `external_id` must remain stable for that source. Both are nonempty strings, at most 100 and 200 characters respectively. Title and summary are nonempty strings of at most 100 and 1500 characters; URL is at most 400 characters and must be HTTPS, without credentials, and use an exact allowed hostname and default HTTPS port. Season is integer 27. `published_at` is a required nonnegative Unix timestamp in seconds, no more than 300 seconds ahead of the import time. No age cutoff is imposed. A record's category and publication behavior come only from its trusted source configuration.

Run on the trusted server with a locally controlled config and input file:

```sh
python fut_ingest.py --config sources.json --input batch.json --database var/community.sqlite3 --actor 1237241595674361962 --owner 1237241595674361962
```

The supplied `--owner` defines the locally trusted staff ID for this CLI invocation; `--actor` must match it. This is not remote authentication: protect command invocation, files and database with operating-system permissions, and do not expose this CLI as a public HTTP endpoint. Python callers can use `ingest_batch(store, actor, records, sources, now)`, passing the `sources` mapping inside the configuration and an existing `CommunityStore` whose staff list authorizes the actor. `now` is an integer Unix timestamp in seconds.

The return value and CLI output are an array of `{index, code}` objects in input order, with no record content. Codes are `draft`, `approved`, `duplicate`, `unknown_source`, `source_disabled`, `invalid_source`, `invalid_record`, `invalid_url`, or `storage_error`. One bad record does not stop the others. Invalid batch shape, more than 100 records, invalid time, or an unauthorized actor rejects the whole call. The CLI exits nonzero for rejected records or a batch-level failure. Existing duplicates are left unchanged, including their original status. The `fut_ingest_metadata` table records source ID, external ID, original publication time, import time and the linked content ID. A transaction inserts content and metadata together, and the `(source_id, external_id)` primary key prevents duplicate inserts.
