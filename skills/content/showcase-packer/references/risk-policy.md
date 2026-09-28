# Material Risk Policy

The preview classifies a material as excluded when its file name, extension, location, or readable text indicates a likely unsafe transfer.

| Risk | Default behavior | Explicit exception |
| --- | --- | --- |
| Credential or private key | Exclude | Never include; replace with a redacted description. |
| Personal data | Exclude | Only if the user names the exact file and confirms an authorized audience. |
| Raw-sensitive material | Exclude | Only if the user names the exact file and confirms it is portable. |
| Absolute local path in text | Exclude | Replace or redact the path before selecting the file. |

Risk classification is a safeguard, not a proof that a file is safe. The user remains responsible for the audience and legal handling of an allowed exception.
