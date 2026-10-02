final: prev:
let
  python3 = prev.python3.override {
    packageOverrides = pf: pp: {
      oscal = pf.callPackage ../package/oscal { };
      ruf-common = pf.callPackage ../package/ruf-common { };
      jsonschema_rs = pp.jsonschema-rs;
    };
  };
in
{
  inherit python3;
  python3Packages = python3.pkgs;
}
