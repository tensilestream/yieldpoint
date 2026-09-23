"""The cross-language adapter section of the generated integrations page."""


def adapters_section(repository: str) -> str:
    return """<h3>Node and Java graph adapters</h3>
<p>The Node package and Java adapter call the same installed <code>yieldpoint</code>
CLI; they do not carry a copy of the rule engine. Put either verifier node between
generation and apply, then route <code>unverified</code> explicitly.</p>
<pre><code>npm install @tensilestream/yieldpoint-langgraph @langchain/langgraph
mvn dependency:get -Dartifact=io.github.tensilestream:yieldpoint-langgraph4j:VERSION</code></pre>
<p>See the runnable <a href="%s/tree/main/examples/node/langgraph_repair_loop.mjs">Node example</a>
and <a href="%s/tree/main/examples/java/LangGraphRepairLoop.java">Java example</a>. The
<a href="%s/blob/main/docs/cli.md">CLI JSON contract</a> covers graph, hook and CI
integrations.</p>""" % (repository, repository, repository)
