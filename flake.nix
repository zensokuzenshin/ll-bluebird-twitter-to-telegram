{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/e06158e58f3adee28b139e9c2bcfcc41f8625b46";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    { nixpkgs, flake-utils, ... }@inputs:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config = {
            allowUnfree = true;
            allowUnfreePredicate = (_: true);
          };
        };
      in
      {
        devShell = pkgs.mkShell {
          buildInputs = with pkgs; [
            python313Full
            black
            ruff
          ];
        };
      }
    );
}
