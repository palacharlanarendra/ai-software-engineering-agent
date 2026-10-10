from app.agent.repair import apply_proposed_python_fix

proposed_source = '''def greet(name):
    print(f"Hello, {name}!")
'''

result = apply_proposed_python_fix(
    "tmp/syntax_error_demo.py",
    proposed_source,
)

print(result)
