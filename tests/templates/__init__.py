"""YAML templates for test applications."""
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent


def load_template(template_name: str, **kwargs) -> str:
    """Load a YAML template and format it with provided variables.
    
    Args:
        template_name: Name of template file (e.g., 'http-debug-app-values.yaml')
        **kwargs: Variables to substitute in the template
    
    Returns:
        str: Formatted YAML content
    
    Example:
        >>> yaml = load_template('http-debug-app-values.yaml', 
        ...                      hostname='app.example.com', 
        ...                      replicas=2)
    """
    template_path = TEMPLATES_DIR / template_name
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_name}")
    
    template_content = template_path.read_text()
    return template_content.format(**kwargs)
