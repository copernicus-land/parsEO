::: {align="center"}
# parsEO

**parsEO** is a Python toolkit that parses existing Earth Observation filenames into structured metadata and assembles new filenames from validated fields. Filename rules live in JSON schemas, turning the repository into a single source of truth for product nomenclature.
:::

## Why parsEO?

-   **Bidirectional workflows** – convert filenames to Python dictionaries and rebuild filenames from the same fields.
-   **Schema-driven** – JSON schemas define every product token, validation rule, and STAC link. Drop in a new schema file and it is discovered automatically.
-   **Extensible** – contributions focus on data, not glue code. Adding support for a new mission only requires a schema.

## Supported product families

-   **Sentinel missions** – S1, S2, S3, S4, S5P, S6
-   **Landsat** – LT04, LT05, LE07, LC08, LC09
-   **NASA MODIS** – Terra and Aqua MODIS products
-   **EUMETSAT missions** – MTG, Metop
-   **Copernicus Land Monitoring Service (CLMS)**
    -   Corine Land Cover (CLC) and CLC+ Raster
    -   European Ground Motion Service (EGMS) Level 2 basic/calibrated products, Level 3 velocity grid, and GNSS model
    -   Urban Atlas Land Cover / Land Use
    -   High Resolution Vegetation Phenology & Productivity (HR-VPP): Seasonal Trajectories (PPI) and Vegetation Indices (FAPAR, LAI, NDVI, PPI, FCOVER, DMP)
    -   High Resolution Water & Snow / Ice (HR-WSI): CC, FSC, GFSC, ICD, SWS, WDS, WIC, WIC-COMB, SP_S2, SP_COMB
    -   High Resolution Layers (HRL): Forest Type, Grassland, Imperviousness, Non-Vegetated Land Cover Characteristics, Tree Cover Density, Water & Wetness, Small Woody Features

## Installation

``` bash
pip install parseo
```

For development installs:

``` bash
git clone https://github.com/copernicus-land/parsEO.git
cd parsEO
pip install -e .
```

Confirm the CLI is available:

``` bash
parseo --version
```

## Quick start

### Parse a filename

``` python
from parseo import parse_auto

name = "S2B_MSIL2A_20241123T224759_N0511_R101_T03VUL_20241123T230829.SAFE"
result = parse_auto(name)

print(result.valid)   # True
print(result.fields)  # structured dict of extracted fields
```

Another example using a MODIS filename:

``` python
from parseo import parse_auto

name = "MOD09GA.A2021123.h18v04.006.2021132234506.hdf"
result = parse_auto(name)

print(result.fields["platform"])  # MOD
print(result.fields["product"])   # 09
print(result.fields["variant"])   # GA
```

The MODIS schema advertises the Processing, Sat, Raster, and Electro-Optical STAC extensions, enabling automated STAC metadata generation (`processing`, `sat`, `raster`, `eo`).

### Assemble a filename

``` python
from parseo import assemble, assemble_auto

fields = {
    "platform": "S2B",
    "instrument": "MSI",
    "processing_level": "L2A",
    "sensing_datetime": "20241123T224759",
    "processing_baseline": "N0511",
    "relative_orbit": "R101",
    "tile_id": "T03VUL",  # MGRS tile (TxxYYY, e.g. T32TNS)
    "generation_datetime": "20241123T230829",
    "extension": "SAFE",
}

assemble_auto(fields)
# 'S2B_MSIL2A_20241123T224759_N0511_R101_T03VUL_20241123T230829.SAFE'

assemble(fields, family="S2")
# Uses the default (current) Sentinel-2 schema for quicker resolution.

assemble(fields, family="S2", version="1.0.0")
# Lock both family and schema version explicitly.
```

To force a specific schema file:

``` python
from pathlib import Path
from parseo import assemble

schema_path = Path("src/parseo/schemas/copernicus/sentinel/s2/s2_filename_v1_0_0.json")
filename = assemble(fields, schema_path=schema_path)
```

`parse_auto` reports the schema version and lifecycle status that were used:

``` python
from parseo import parse_auto

result = parse_auto("S2B_MSIL2A_20241123T224759_N0511_R101_T03VUL_20241123T230829.SAFE")
print(result.version)  # '1.0.0'
print(result.status)   # 'current'
```

### Command-line interface

The same functionality is exposed through the CLI.

``` bash
# Parse a filename
parseo parse S2B_MSIL2A_20241123T224759_N0511_R101_T03VUL_20241123T230829.SAFE

# Parse a Copernicus Land Monitoring Service (CLMS) filename
parseo parse ST_20240101T123045_S2_E15N45-03035-010m_V100_PPI.tif

# Parse and write the JSON response to a file
parseo parse ST_20240101T123045_S2_E15N45-03035-010m_V100_PPI.tif --output result.json

# Assemble from the saved JSON document. The CLI automatically
# extracts the `fields` entry produced by `parseo parse`.
cat result.json | parseo assemble --family copernicus:clms:hr-vpp:st --fields-json -

# Pipe the parse result directly into assemble
parseo parse ST_20240101T123045_S2_E15N45-03035-010m_V100_PPI.tif \
  | parseo assemble --family copernicus:clms:hr-vpp:st

# Assemble the same CLMS filename from key=value pairs
parseo assemble
  product=ST
  timestamp=20240101T123045 
  sensor=S2
  tile_id=E15N45
  epsg_code=03035
  resolution=010m
  version=V100
  variable=PPI
  extension=tif
```

### Discover available schemas

List every schema that ships with parsEO, including its fully qualified `schema_id`, semantic version, lifecycle status, and file location:

``` bash
parseo list-schemas
```

The command prints a table summarizing all discovered schemas, making it easy to confirm which versions are available before parsing or assembling filenames. The first column shows the complete namespace (for example `copernicus:clms:hrl:vlcc`), so you can see exactly where a product sits inside the Copernicus hierarchy.

List only the schemas that are marked as `current` with the built-in filter (works on every platform):

``` bash
parseo list-schemas --status current
```

To inspect a single family in the summary table, provide the short family name explicitly. You can also pass a namespace prefix to see every schema beneath it:

``` bash
parseo list-schemas --family S2
parseo list-schemas --family copernicus
parseo list-schemas --family copernicus:clms:hrl
```

For the full schema metadata (fields, examples, etc.), use `schema-info`:

``` bash
parseo schema-info S2
```

The JSON response includes the schema's semantic version and lifecycle status so
you can immediately tell which release you are viewing. To inspect an archived
version, provide the version number explicitly:

``` bash
parseo schema-info --version 1.0.0 CLC
```

### Working with specific schema versions

When multiple schema versions are present, parsEO chooses the one whose `status` is `"current"`. If none are marked current, the highest `schema_version` wins. You can inspect historical schemas with `parseo schema-info --version <x.y.z> <family>` and you can always pin a schema by passing `schema_path` to `assemble` or `parse`.

## Authoring new Schema

Adding a schema requires only a JSON document under `src/parseo/schemas/`. Start from an existing product schema or the skeleton in `template/`.

-   **Create the product directory** – `src/parseo/schemas/<family>/<mission>/<product>/` (only the family level is mandatory).

-   **Write the versioned schema file** – `<product>_filename_vX_Y_Z.json` with required metadata (`schema_id`, `schema_version`, `status`, optional `stac_version`, `stac_extensions`, and `description`).

-   **Maintain versions** — mark the latest schema as `"current"` and move older ones to `"deprecated"` (or similar). parsEO uses these flags to pick defaults.

    **Schema versioning policy:** Schemas at version `0.0.0` are provisional — their patterns and field definitions may change without notice. Once a product's naming convention is finalised (typically when it reaches CDSE production), the schema should be promoted to `1.0.0` to signal a stable, supported contract.

### Container Object `fields`

**`fields`** is a container object to define filename tokens and translation mechanisms from/to STAC. Each `property` combines JSON Schema keywords (`type`, `pattern`, `enum`, …) and optional documentation. The `property name` is the variable name used by the `template` container and unless a `stac_map` is applied also what is retrieved by `parseo parse` or fed into `parseo assemble`.

``` json
"fields": { 
  "property-1": {
    "type": "string", 
    "enum": ["A","B"], 
    "description": "descripton of property 1"
  },
  "property-2": {
    "type": "string", 
    "pattern": "^(\d{8}T\d{6})$", 
    "description": "descripton of property 2"
  },
  ...
}
```

#### `type`

The keyword `type` is currently set to "string" by default, and used as best practice.

#### `enum` or `pattern`

-   Use `enum` for short, controlled vocabularies such as file extensions or processing modes (`["A","B"]`). It keeps validation strict and self-documenting.
-   Use `pattern` for structured tokens like timestamps (`^\d{8}T\d{6}$`), version identifiers (`^V\d{3}$`), or grid identifiers (`^h\d{2}v\d{2}$`).

#### `oneOf`

Use `oneOf` to express mutually exclusive validation branches for a single field. Each branch can provide its own JSON Schema keywords, enabling concise modelling of tokens that admit multiple formats. For example, a `variant` token may allow either a fixed set of legacy values or a future-proof pattern:

``` json
"variant": {
  "type": "string",
  "oneOf": [
    {"enum": ["A", "B", "C"]},
    {"pattern": "^X\d{2}$"},
    {"pattern": "^z\d{4}$"}
  ],
  "description": "Legacy letters or experimental codes"
}
```

When `parseo parse` runs, the value is checked against each branch in order until one succeeds. `parseo assemble` accepts any value satisfying at least one branch, allowing schemas to stay expressive without duplicating fields.

#### `stac_map`

Functionality to connect filename tokens to STAC properties in case of incompatibility. In the following example `parseo parse` matches the filename field `prefix` but returns the STAC compliant `platform` and `instrument`. `parseo assemble` must be provided with `platform` and `instrument` and converts it to the correct `prefix` as defined by the filename `template`.

``` json
"prefix": {
  "type": "string",
  "pattern": "^(MOD|MYD|MCD)$",
  "stac_map": {
    "MOD": {
      "platform": "Terra", 
      "instrument": "MODIS"
    },
    "MYD": {
      "platform": "Aqua", 
      "instrument": "MODIS"
    },
    "MCD": {
      "platform": "Combined", 
      "instrument": "MODIS"
    }
  }
}
```


#### Container Object `template`
A filename is assembled/parsed based on the definition put into `template` container object. E.g.:

``` json
"template": "{variable}-C{reference_year}_R{resolution}_{tile_id}{epsg_code}_{version}[.{extension}]"
```

`fields` are added to the `template` using the `{property name}`. The template further decides for the fields are arranged and how they are separated from each other. Further it is possible to ad permanent elements as well, e.g. adding a prefix `C` to the `{reference_year} = C{reference_year}` to match e.g. 'C2012'. This can be particularly useful if you are interested in only parts of the field, e.g. by doping `EPSG{epsg_code}` you fetch only the code itself. This can also be a regex, e.g. `..._(S|C){reference_year}_...`.

Optional filenames must be encapsulated in `[]`. E.g. `[.{extension}]`

#### Container Object `examples` 

Populate `"examples"` with valid filenames covering typical combinations of optional tokens. Test routines will run the examples to assess the proper functioning.

### Test round-trips

run `parseo parse <filename>` and `parseo assemble --schema <schema_path>` to confirm the schema behaves as expected.

### Run unit tests

Install the pytest python package.

from the top-level directory, run `pytest` to launch all tests, or e.g `pytest tests/test_schema_examples_round_trip.py`

### Run as API

parsEO functions can be exposed through a web service. The example below uses [FastAPI](https://fastapi.tiangolo.com), which provides an automatic Swagger UI for trying out the endpoints.

``` python
# Safe to file: main.py
from fastapi import FastAPI
from parseo import assemble, parse_auto

app = FastAPI()

@app.get("/parse")
def parse_endpoint(name: str):
    res = parse_auto(name)
    return res

@app.post("/assemble")
def assemble_endpoint(schema: str, fields: dict):
    filename = assemble(fields, schema_path=schema)
    return {"filename": filename}
```

Install fastapi and uvicorn (in a python virtual environment):

``` bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the required dependencies (fastapi and uvicorn):

``` bash
(.venv) pip install fastapi uvicorn[standard]
```

from the console inside the same directory start the app:

``` bash
(.venv) python -m uvicorn main:app --reload
```

Open <http://127.0.0.1:8000/docs> to access Swagger UI:

The interactive page lets you call `/parse` and `/assemble` directly from the browser to verify the API.


## Contributing

-   Place new schemas under `src/parseo/schemas/<product_family>/`.
-   Include at least one positive example in each schema file.
-   Run the test-suite with `pytest` (and `ruff check .` for linting) before opening a pull request.
-   Submit a pull request describing the new products or fixes.

## License

This project is licensed under the [European Union Public Licence v1.2](LICENSE.txt).
