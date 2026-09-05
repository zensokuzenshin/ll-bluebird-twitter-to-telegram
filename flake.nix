{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    { nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        devShells.default = pkgs.mkShell {
          # ruff covers both formatting and linting, so black is gone.
          # Python packages come from uv, not nixpkgs.
          packages = with pkgs; [
            python314
            ruff
            uv
          ];
        };
      }
    );
}
