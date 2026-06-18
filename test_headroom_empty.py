from headroom.transforms.code_compressor import CodeAwareCompressor, CodeCompressorConfig, DocstringMode
config = CodeCompressorConfig(docstring_mode=DocstringMode.REMOVE)
compressor = CodeAwareCompressor(config=config)
code = """
public final class MessageFetchJob extends BaseJob {
  public MessageFetchJob() {
    this(new Job.Parameters.Builder().build());
  }
}
"""
res = compressor.compress(code, language="java")
print("LEN:", len(res.compressed))
print("RES:", repr(res.compressed))
