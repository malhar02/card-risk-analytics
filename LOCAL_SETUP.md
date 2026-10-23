# Local setup: PySpark on Windows

This project runs Spark locally through the `pyspark` Python package; a separate Apache Spark download is not required. The development machine already has Microsoft OpenJDK 17 and a project `.venv` with PySpark 4.2.0.

## Reopen VS Code and prepare the terminal

If a new PowerShell terminal cannot find Java, set the Java variables for that terminal session. The installed path used during development was:

```powershell
$env:JAVA_HOME = "C:\Program Files\Microsoft\jdk-17.0.20.101-hotspot"
$env:Path = "$env:JAVA_HOME\bin;$env:Path"
java -version
```

Confirm the output says Java 17 or later. These PowerShell variables last for the current terminal session.

## Install or refresh Python dependencies

From the project root:

```powershell
python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r ".\requirements.txt"
```

If `.venv` already exists and is working, you can skip the `venv` creation line. Always run project scripts with `& ".\.venv\Scripts\python.exe" ...` so VS Code does not substitute a global Python without PySpark.

## Windows Spark messages

Spark may print a warning that `winutils.exe` or the native Hadoop library is unavailable. The analysis scripts use Spark for local reads and computation, then stream the small result sets to CSV with Python’s standard library. They do not use Spark’s local Hadoop CSV writer, which can fail on Windows without `winutils.exe`.

The PySpark warning about pandas versions means Spark does not fully support pandas 3 yet. `requirements.txt` keeps local pandas below version 3.

## Azure Databricks

Azure Databricks supplies its own Spark runtime, so do not install the local `.venv` on the cluster. Import `notebooks/azure_databricks_pipeline.py` as a notebook, set the Unity Catalog Volume and target schema widgets, and use the access permissions documented in the main README.
