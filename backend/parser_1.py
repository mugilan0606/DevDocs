import os
import ast
import json

try:
    import pydot
    import networkx as nx
    GRAPH_LIBS = True
except ImportError:
    GRAPH_LIBS = False

LOCAL_REPO_DIR = "code_repo"
OUTPUT_JSON = "code_flow.json"
common_functions = {
    "print", "open", "dumps", "loads", "range", "len", "int", "str", "float",
    "list", "dict", "set", "tuple", "sum", "min", "max", "abs", "round",
    "sorted", "reversed", "enumerate", "zip", "map", "filter", "reduce",
    "any", "all", "isinstance", "issubclass", "hasattr", "getattr", "setattr",
    "delattr", "globals", "locals", "vars", "dir", "help", "id", "type",
    "callable", "eval", "exec", "compile", "format", "input", "next", "iter",
    "super", "staticmethod", "classmethod", "property"
}

# List Python files function
def list_python_files(directory):
    """Recursively finds and prints all .py files in the given directory."""
    python_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                python_files.append(os.path.join(root, file))
    return python_files

# Extract function definitions and their calls from a Python file
def extract_functions(file_path):
    """Extracts function definitions and their calls from a Python file."""
    with open(file_path, "r", encoding="utf-8") as file:
        tree = ast.parse(file.read(), filename=file_path)

    functions = {"file_path": file_path}
    imports = {"modules": [], "functions": []}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports["modules"].append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module
            for alias in node.names:
                imports["functions"].append(f"{module}.{alias.name}")
    functions["imports"] = imports
    
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):  # Extract function names
            func_name = node.name
            functions[func_name] = {"calls": [], "import_calls": []}  # Add function code

            # Find function calls inside this function
            for child in ast.walk(node):
                dont_add = False
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                    # Store function calls
                    
                    # Check if the function call is an import
                    for object in imports["functions"]:
                        if child.func.id in object.split(".")[-1]:
                            functions[func_name]["import_calls"].append(object)  # Store import calls
                            dont_add = True
                            continue
                    if child.func.id in imports["modules"]:
                        functions[func_name]["import_calls"].append(child.func.id)
                        dont_add = True
                        continue
                    if not dont_add and child.func.id not in common_functions:
                        functions[func_name]["calls"].append(child.func.id)

    return functions

# Analyzing code flow for all Python files
def analyze_code_flow(repo_dir):
    """Scans all Python files and analyzes function relationships, saving the output as JSON."""
    code_flow = {}

    # Extract function definitions and calls from each file
    for file_path in list_python_files(repo_dir):
        functions = extract_functions(file_path)
        if functions:  # Only include files that have functions
            code_flow[os.path.basename(file_path)] = functions

    # Save to JSON file
    with open(OUTPUT_JSON, "w", encoding="utf-8") as json_file:
        json.dump(code_flow, json_file, indent=4)

    print(f"✅ Code flow saved to {OUTPUT_JSON}")
    return code_flow


def create_pydot_flowchart(code_flow):
    """Creates flowcharts of the code flow using pydot and saves them as images for each disconnected graph."""
    if not GRAPH_LIBS:
        print("[WARN] pydot/networkx not installed — skipping flowchart generation.")
        return
    graph = pydot.Dot(graph_type='digraph')

    for file, functions in code_flow.items():
        for func, details in functions.items():
            if func == "file_path" or func == "imports":
                continue
            func_node = pydot.Node(f"{func}\n({file})", shape='ellipse')
            graph.add_node(func_node)
            for call in details["calls"]:
                call_node = pydot.Node(call, shape='box')
                graph.add_node(call_node)
                graph.add_edge(pydot.Edge(call, f"{func}\n({file})"))
            for import_call in details["import_calls"]:
                import_node = pydot.Node(import_call, shape='diamond')
                graph.add_node(import_node)
                graph.add_edge(pydot.Edge(import_call, f"{func}\n({file})"))
        for module in functions["imports"]["modules" ]:
            module_node = pydot.Node(module, shape='hexagon')
            graph.add_node(module_node)
            graph.add_edge(pydot.Edge(module, f"{func}\n({file})"))

    # Identify connected components
    subgraphs = nx.weakly_connected_components(nx.nx_pydot.from_pydot(graph))
    for i, component in enumerate(subgraphs):
        if len(component) == 1:  # Ignore disconnected single nodes
            continue
        subgraph = pydot.Dot(graph_type='digraph')
        for node in component:
            subgraph.add_node(graph.get_node(node)[0])
        for edge in graph.get_edges():
            if edge.get_source() in component and edge.get_destination() in component:
                subgraph.add_edge(edge)
        
        # Use a different layout to ensure the image size remains within bounds
        subgraph.set_splines('true')
        subgraph.set_overlap('false')
        subgraph.set_rankdir('LR')  # Left to Right layout

        subgraph.write_png(f"./code_flowchart/code_flowchart_component_{i+1}.png")
        print(f"->  Flowchart saved as code_flowchart_component_{i+1}.png")

if __name__ == "__main__":
    if not os.path.exists('code_flowchart'):
        os.makedirs('code_flowchart')
    code_flow = analyze_code_flow(LOCAL_REPO_DIR)
    create_pydot_flowchart(code_flow)


