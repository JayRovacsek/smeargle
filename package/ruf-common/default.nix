{
  lib,
  buildPythonPackage,
  fetchPypi,
  setuptools,
  elementpath,
  pytz,
  tzlocal,
  geopy,
  timezonefinder,
  aiohttp,
  requests,
  pycountry,
  html2text,
  packaging,
  pyyaml,
}:

buildPythonPackage rec {
  pname = "ruf-common";
  version = "2.2.0";
  pyproject = true;

  src = fetchPypi {
    pname = "ruf_common";
    inherit version;
    hash = "sha256-NwpwCrC1jwPGqH/r77SdrL7lTbKSjwApMSU8RN+DZkA=";
  };

  build-system = [ setuptools ];

  dependencies = [
    elementpath
    pytz
    tzlocal
    geopy
    timezonefinder
    aiohttp
    requests
    pycountry
    html2text
    packaging
    pyyaml
  ];

  doCheck = false;
  pythonImportsCheck = [ "ruf_common" ];

  meta = {
    description = "Functions common to several Python projects by Brian Ruf";
    homepage = "https://github.com/brian-ruf/ruf-common-python";
    license = lib.licenses.mit;
  };
}
