{
  description = "smeargle: map RFC 2119 requirements to OSCAL control catalogs";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      flake-utils,
      nixpkgs,
      ...
    }:
    flake-utils.lib.eachSystem
      [
        "x86_64-linux"
        "aarch64-linux"
      ]
      (
        system:
        let
          pkgs = import self.inputs.nixpkgs { inherit system; };
          py = pkgs.python3Packages;
          smeargle = py.buildPythonApplication {
            pname = "smeargle";
            version = "0.1.0";
            pyproject = true;
            src = pkgs.lib.cleanSourceWith {
              src = ./.;
              filter =
                path: type:
                let
                  root = toString ./.;
                  rel = pkgs.lib.removePrefix (root + "/") (toString path);
                in
                rel == "pyproject.toml"
                || rel == "src"
                || rel == "tests"
                || pkgs.lib.hasPrefix "src/" rel
                || pkgs.lib.hasPrefix "tests/" rel;
            };
            build-system = [ py.setuptools ];
            dependencies = with py; [
              typer
              pydantic
              pydantic-settings
              httpx
              pyyaml
            ];
            nativeCheckInputs = [ py.pytestCheckHook ];
            pythonImportsCheck = [ "smeargle" ];
            meta = {
              description = "Map RFC 2119 requirements to OSCAL control catalogs";
              mainProgram = "smeargle";
            };
          };
        in
        {
          packages = {
            inherit smeargle;
            default = smeargle;
          };

          devShells.default = pkgs.mkShell {
            packages = [
              (pkgs.python3.withPackages (ps: [
                ps.typer
                ps.pydantic
                ps.pydantic-settings
                ps.httpx
                ps.pyyaml
                ps.pytest
              ]))
              py.ruff
              py.mypy
            ];
            shellHook = ''
              export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
            '';
          };

          checks.default = self.packages.${system}.smeargle;

          apps.default = {
            type = "app";
            program = "${self.packages.${system}.smeargle}/bin/smeargle";
          };
        }
      );
}
