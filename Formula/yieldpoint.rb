class Yieldpoint < Formula
  desc "Deterministic verification for agents that write code"
  homepage "https://github.com/tensilestream/yieldpoint"
  url "https://github.com/tensilestream/yieldpoint/archive/refs/tags/v0.1.4.tar.gz"
  sha256 "e6d24a9263aed29251e53c5869da7848797d4c25b29bc983d6cd11f67b6c8ec0"
  license "BUSL-1.1"

  depends_on "python"

  def install
    libexec.install Dir["*"]
    (bin / "yieldpoint").write <<~EOS
      #!/bin/bash
      export PYTHONPATH="#{libexec}:${PYTHONPATH:-}"
      exec "#{Formula["python"].opt_bin}/python3" -m yieldpoint "$@"
    EOS
    bin.install_symlink "yieldpoint" => "yp"
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/yieldpoint --version")
    assert_match "unverified", shell_output("#{bin}/yieldpoint check --path sample.py --before /dev/null --after /dev/null --json", 3)
    assert_match version.to_s, shell_output("#{bin}/yp --version")
  end
end
