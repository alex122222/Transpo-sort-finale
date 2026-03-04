import sys
import subprocess

def check_and_fix():
    print(f"Current Python Interpreter: {sys.executable}")
    print(f"Python Version: {sys.version}")
    
    try:
        import networkx as nx
        print(f"SUCCESS: 'networkx' is already installed (version: {nx.__version__})")
    except ImportError:
        print("ERROR: 'networkx' is NOT installed in this environment.")
        print("Attempting to install dependencies from requirements.txt...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
            import networkx as nx
            print(f"SUCCESS: 'networkx' has been installed (version: {nx.__version__})")
        except Exception as e:
            print(f"CRITICAL ERROR: Failed to install dependencies: {e}")
            return

    print("\n--- ACTION REQUIRED ---")
    print("If your IDE (like VS Code) still shows an error:")
    print(f"1. Open your IDE's Python Interpreter settings.")
    print(f"2. Ensure it is pointing to: {sys.executable}")
    print("3. Restart your IDE or the Python language server if necessary.")

if __name__ == "__main__":
    check_and_fix()
