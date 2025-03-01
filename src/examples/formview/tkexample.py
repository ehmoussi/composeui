import tkinter as tk
from tkinter import filedialog, ttk


def create_interface() -> None:
    # Initialize main window
    root = tk.Tk()
    root.title("Example")
    root.geometry("600x400")  # Set window size

    # Menu bar
    menu = tk.Menu(root)
    file_menu = tk.Menu(menu, tearoff=0)
    file_menu.add_command(label="New")
    file_menu.add_command(label="Open")
    file_menu.add_command(label="Save")
    file_menu.add_command(label="Exit", command=root.quit)
    menu.add_cascade(label="File", menu=file_menu)
    root.config(menu=menu)

    # Notebook (Tabs)
    notebook = ttk.Notebook(root)
    tab_pipe = ttk.Frame(notebook)
    notebook.add(tab_pipe, text="Pipe")
    notebook.pack(expand=True, fill="both")

    # Pipe Settings Frame
    frame_pipe = ttk.LabelFrame(tab_pipe, text="Pipe")
    frame_pipe.pack(fill="both", padx=10, pady=10)

    # Name Entry
    ttk.Label(frame_pipe, text="Name").grid(row=0, column=0, padx=5, pady=5, sticky="w")
    name_entry = ttk.Entry(frame_pipe)
    name_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

    # Export File Button
    ttk.Label(frame_pipe, text="Export File").grid(row=1, column=0, padx=5, pady=5, sticky="w")
    export_entry = ttk.Entry(frame_pipe)
    export_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
    export_button = ttk.Button(
        frame_pipe, text="...", command=lambda: filedialog.askopenfilename()
    )
    export_button.grid(row=1, column=2, padx=5, pady=5)

    frame_pipe.columnconfigure(1, weight=1)

    # Main Pipe Settings
    main_pipe_frame = ttk.LabelFrame(frame_pipe, text="Main Pipe")
    main_pipe_frame.grid(row=2, column=0, columnspan=3, padx=5, pady=5, sticky="ew")

    ttk.Label(main_pipe_frame, text="Radius").grid(row=0, column=0, padx=5, pady=5)
    radius_main = ttk.Entry(main_pipe_frame)
    radius_main.grid(row=0, column=1, padx=5, pady=5)

    ttk.Label(main_pipe_frame, text="Width").grid(row=1, column=0, padx=5, pady=5)
    width_main = ttk.Entry(main_pipe_frame)
    width_main.grid(row=1, column=1, padx=5, pady=5)

    ttk.Label(main_pipe_frame, text="Half Length").grid(row=2, column=0, padx=5, pady=5)
    half_length_main = ttk.Entry(main_pipe_frame)
    half_length_main.grid(row=2, column=1, padx=5, pady=5)

    # Incident Pipe Settings
    incident_pipe_frame = ttk.LabelFrame(frame_pipe, text="Incident Pipe")
    incident_pipe_frame.grid(row=3, column=0, columnspan=3, padx=5, pady=5, sticky="ew")

    ttk.Label(incident_pipe_frame, text="Radius").grid(row=0, column=0, padx=5, pady=5)
    radius_incident = ttk.Entry(incident_pipe_frame)
    radius_incident.grid(row=0, column=1, padx=5, pady=5)

    ttk.Label(incident_pipe_frame, text="Width").grid(row=1, column=0, padx=5, pady=5)
    width_incident = ttk.Entry(incident_pipe_frame)
    width_incident.grid(row=1, column=1, padx=5, pady=5)

    ttk.Label(incident_pipe_frame, text="Half Length").grid(row=2, column=0, padx=5, pady=5)
    half_length_incident = ttk.Entry(incident_pipe_frame)
    half_length_incident.grid(row=2, column=1, padx=5, pady=5)

    # Edge Type
    edge_type_frame = ttk.LabelFrame(frame_pipe, text="Edge Type")
    edge_type_frame.grid(row=4, column=0, columnspan=3, padx=5, pady=5, sticky="ew")

    edge_type_var = tk.StringVar(value="Normal")
    ttk.Radiobutton(
        edge_type_frame, text="Normal", variable=edge_type_var, value="Normal"
    ).pack(side="left", padx=5, pady=5)
    ttk.Radiobutton(
        edge_type_frame, text="Chamfer", variable=edge_type_var, value="Chamfer"
    ).pack(side="left", padx=5, pady=5)
    ttk.Radiobutton(
        edge_type_frame, text="Fillet", variable=edge_type_var, value="Fillet"
    ).pack(side="left", padx=5, pady=5)

    root.mainloop()


# Run the interface
create_interface()
