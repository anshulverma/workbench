# providers/doc_reader

**Purpose:** the `DocReader` provider interface — for reading documents
referenced by items.

**Status: latent / unwired.** Only the base ABC exists (`base.py`); there is no
concrete implementation yet, and `DocReader` is not referenced in YAML config or
elsewhere in the code. The interface family is reserved so the convention and
registry path are in place when a reader is added.

**What belongs here:** the `DocReader` base interface and, in future, concrete
implementations.

**What does NOT belong here:** other provider families, or doc-fetching wired
into pipeline stages before a concrete reader exists.

**Update this README when** you add a KIND of code here — notably the first
concrete `DocReader` implementation (and remove the "latent/unwired" note once
it is wired into config).
