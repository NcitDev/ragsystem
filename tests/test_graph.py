import pytest
from rag.core.graph import CodeGraph

def test_code_graph_traversal_prunes_imports():
    graph = CodeGraph()
    chunks = [
        {
            "file_path": "a.py",
            "name": "ClassA",
            "chunk_type": "class_declaration",
            "language": "python",
            "calls": ["b.py:ClassB"],
            "imports": ["c.py"]
        },
        {
            "file_path": "b.py",
            "name": "ClassB",
            "chunk_type": "class_declaration",
            "language": "python",
        },
        {
            "file_path": "c.py",
            "name": "ClassC",
            "chunk_type": "class_declaration",
            "language": "python",
        }
    ]
    graph.build_from_chunks(chunks)
    
    node_id_a = "a.py:ClassA"
    
    # Traverse from ClassA. BFS should follow calls edge to ClassB, but skip imports edge to ClassC
    nodes = graph.traverse(node_id_a, max_hops=2, direction="both")
    
    assert "b.py:ClassB" in nodes
    assert "c.py:ClassC" not in nodes
    assert "import:c.py" not in nodes
