{
  description = "smeargle: map RFC 2119 requirements to OSCAL control catalogues";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    git-hooks = {
      url = "github:cachix/git-hooks.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    devshell = {
      url = "github:numtide/devshell";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      flake-utils,
      nixpkgs,
      git-hooks,
      devshell,
      ...
    }:
    let
      overlay = import ./overlays/default.nix;
    in
    (flake-utils.lib.eachSystem
      [
        "x86_64-linux"
        "aarch64-linux"
      ]
      (
        system:
        let
          pkgs = import nixpkgs {
            inherit system;
            overlays = [
              overlay
              devshell.overlays.default
            ];
          };
          py = pkgs.python3Packages;
          smeargle = py.buildPythonApplication {
            pname = "smeargle";
            version = "0.1.0";
            pyproject = true;
            src = pkgs.lib.cleanSourceWith {
              src = ./.;
              filter =
                path: _type:
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
              oscal
              pypdf
              python-docx
              openai
              rich
            ];
            nativeCheckInputs = [
              py.pytestCheckHook
              py.jsonschema-rs
              py.respx
            ];
            pythonImportsCheck = [ "smeargle" ];
            meta = {
              description = "Map RFC 2119 requirements to OSCAL control catalogues";
              mainProgram = "smeargle";
            };
          };
          pre-commit-check = git-hooks.lib.${system}.run {
            src = ./.;
            hooks = {
              deadnix = {
                enable = true;
                settings.noUnderscore = true;
              };
              nixfmt.enable = true;
              prettier.enable = true;
              ruff.enable = true;
              statix.enable = true;
              trufflehog.enable = true;
              typos = {
                enable = true;
                settings.locale = "en-au";
              };
            };
          };
        in
        {
          packages = {
            inherit smeargle;
            default = smeargle;
          };

          devShells.default = pkgs.devshell.mkShell {
            name = "smeargle";
            packages = [
              (pkgs.python3.withPackages (ps: [
                ps.typer
                ps.pydantic
                ps.pydantic-settings
                ps.httpx
                ps.pyyaml
                ps.oscal
                ps.pypdf
                ps.python-docx
                ps.jsonschema-rs
                ps.pytest
                ps.respx
                ps.openai
                ps.rich
              ]))
              py.mypy
              # hook tools, available directly in the shell
              pkgs.deadnix
              pkgs.nixfmt
              pkgs.prettier
              pkgs.ruff
              pkgs.statix
              pkgs.trufflehog
              pkgs.typos
            ];
            env = [
              {
                name = "PYTHONPATH";
                eval = "$PRJ_ROOT/src";
              }
            ];
            # wire the git hooks into the shell so commits run the checks
            devshell.startup.pre-commit.text = pre-commit-check.shellHook;
          };

          checks = {
            pre-commit = pre-commit-check;
            default = self.packages.${system}.smeargle;
          };

          apps.default = {
            type = "app";
            program = "${self.packages.${system}.smeargle}/bin/smeargle";
          };
        }
      )
    )
    // {
      overlays.default = overlay;
    };
}
