# Rebuild the retained protocol diagram

From the repository root, run:

```sh
mkdir -p build
dot -Tpdf paper/figures/fig1_causal_design.dot -o build/fig1_protocol.pdf
pdftoppm -singlefile -r 150 -png build/fig1_protocol.pdf build/fig1_protocol
```

The source SHA256 is b4e18a6db7a32fa7c3b0e57cb33fa71649fb6dfb9717727e9fc1b5ed59802e47. Graphviz 14.1.1 with Helvetica and Poppler 26.07.0 reproduced the retained Figure 1 at 150 dpi: 1632 by 607 pixels, identical pixel bytes and extracted text. The rebuilt PDF had different bytes; PDF binary identity is not the reproduction criterion. Other versions or font installations may differ. The editable DOT and retained published PDF are unchanged.

The figure is a conceptual workflow, including historical studies and excluded extensions. It contains no new numerical observations. The 102-item branch describes the original primary study; later campaigns reuse or extend its protocol and do not change that historical identity.

Figure 2 remains HOLD. Building the archived TeX succeeds but produces a different page, font and layout with crowded panel headings. It does not recreate the retained revised PDF. Its primary-record/tabulation entry point remains absent from this projection. No reconstructed Figure 2 replaces the paper figure. See FIGURE_BUILD_VERIFICATION.json for the observed hashes, versions and limits.

Licensing and author approval remain pending. This build record establishes reproduction within the recorded rendering environment; it does not certify scientific truth, redistribution permission or publication.
