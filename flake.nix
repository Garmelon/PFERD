{
  description = "Tool for downloading course-related files from ILIAS";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
  };

  outputs = { self, nixpkgs }:
    let
      forAllSystems = nixpkgs.lib.genAttrs nixpkgs.lib.systems.flakeExposed;
      project = (nixpkgs.lib.importTOML ./pyproject.toml).project;
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs {
            inherit system;
            overlays = nixpkgs.lib.optionals (nixpkgs.lib.hasSuffix "-freebsd" system) [
              (_final: prev: {
                # Graphviz is used for dependency documentation. Its optional GTS
                # support is unavailable on FreeBSD and is not needed for that.
                graphviz = prev.graphviz.override { gts = null; };
              })
            ];
          };
        in
        {
          default = pkgs.python3Packages.buildPythonApplication {
            pname = "pferd";
            version = project.version;
            pyproject = true;

            src = pkgs.lib.cleanSource ./.;

            build-system = with pkgs.python3Packages; [
              setuptools
              wheel
            ];

            dependencies = with pkgs.python3Packages; [
              aiohttp
              beautifulsoup4
              rich
              keyring
              certifi
            ];

            pythonImportsCheck = [ "PFERD.__main__" ];

            meta = {
              description = project.description;
              homepage = project.urls.Repository;
              license = pkgs.lib.getLicenseFromSpdxId project.license;
              mainProgram = "pferd";
              platforms = pkgs.lib.platforms.unix;
            };
          };
        });

      checks = forAllSystems (system: {
        default = self.packages.${system}.default;
      });
    };
}
