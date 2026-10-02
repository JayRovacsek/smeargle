{
  lib,
  buildPythonPackage,
  fetchPypi,
  setuptools,
  jsonschema-rs,
  jsonpath-python,
  xmlschema,
  pyyaml,
  markdown,
  ruf-common,
}:

buildPythonPackage rec {
  pname = "oscal";
  version = "3.2.2";
  pyproject = true;

  src = fetchPypi {
    inherit pname version;
    hash = "sha256-w5F33JBVBOluXpvgvoEQhyoZvvIbia/w25Zs25Mnsk8=";
  };

  build-system = [ setuptools ];

  dependencies = [
    jsonschema-rs
    jsonpath-python
    xmlschema
    pyyaml
    markdown
    ruf-common
  ];

  doCheck = false;
  pythonImportsCheck = [ "oscal" ];

  postInstall = ''
    python - <<'PY'
    from importlib import resources
    archive = resources.files("oscal.data").joinpath("oscal_support.zip")
    assert archive.is_file(), "bundled oscal support database is missing"
    assert archive.stat().st_size > 1_000_000, "bundled oscal support database looks truncated"
    PY
  '';

  meta = {
    description = "Python library to validate, convert, query and mutate OSCAL content";
    homepage = "https://github.com/brian-ruf/oscal-class";
    license = lib.licenses.mit;
    mainProgram = "oscal";
  };
}
