# Mardocx configuration

Place an optional `mardocx.yaml` in the project root. Its fields are merged with Mardocx defaults; omitted values retain the defaults.

```yaml
typography:
  body:
    font: "宋体"
    size_pt: 12
    line_spacing: 1.25
  headings:
    "1": { size_pt: 24, bold: true }
images:
  landscape_width_cm: 8
  portrait_width_cm: 6
  caption:
    color: "#808080"
```

`update-reference` applies typography and caption values to the project's `reference.docx`. Image widths affect each conversion's local-image attributes and do not modify the template. Unknown keys and invalid values stop the command so configuration mistakes are not silently ignored.
