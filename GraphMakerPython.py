import threading  # Permette di eseguire operazioni in parallelo (lettura Bluetooth in background)
import time  # Gestione del tempo e delay per sincronizzare i dati
import numpy as np  # Calcoli matematici avanzati e array numerici per regressioni
import tkinter as tk  # Creazione interfaccia grafica principale
import matplotlib  # Libreria professionale per creazione grafici scientifici
matplotlib.use("TkAgg")  # Backend grafico specifico per integrazione perfetta con Tkinter
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # Widget ponte tra Matplotlib e Tkinter
import matplotlib.pyplot as plt  # Strumenti di disegno e personalizzazione grafici
import serial  # Comunicazione seriale per ricevere dati dall'ESP32 via Bluetooth
import pandas as pd  # Manipolazione dati per esportazione Excel professionale
from tkinter import filedialog  # Finestra nativa sistema per selezione percorsi salvataggio
from tkinter import messagebox  # Popup informativi, di avviso e gestione errori


# ===============================
# CONFIGURAZIONE BLUETOOTH
# ===============================
BT_PORT = "COM7"  # Porta seriale Windows dove è collegato l'ESP32 (modificare se necessario)
BT_BAUD = 115200  # Velocità trasmissione dati standard per ESP32 (115200 baud = molto veloce)


# ===============================
# VARIABILI GLOBALI
# ===============================
secondi = []  # Lista tempi relativi dall'inizio acquisizione (asse X grafico)
umidita = []  # Lista valori umidità % ricevuti dall'ESP32 (asse Y umidità)
temperatura = []  # Lista valori temperatura °C ricevuti dall'ESP32 (asse Y temperatura)
lock = threading.Lock()  # Semaforo mutex per accesso sicuro alle liste da più thread
start_time = time.time()  # Timestamp assoluto inizio acquisizione dati
MODALITA = None  # Memorizza modalità grafico attiva ("umidita", "temperatura", "entrambe")
aggiornamento_attivo = True  # Flag booleano: True=acquisizione/grafico attivi, False=pausa
metriche_label = None  # Widget Label che visualizza statistiche regressione
mostra_metriche = False  # Flag visibilità pannello statistiche (True=visibile)
pulsante_stop = None  # Riferimento al widget pulsante STOP/PLAY per modifica dinamica
ignora_prossimo_dato = False  # Flag per resettare cronometro dopo pausa/ripresa
lista_dati = None  # Widget Listbox che mostra cronologia dati ricevuti
app_in_esecuzione = True  # Flag principale: False termina tutti i thread/background


# ===============================
# FUNZIONE PER AGGIORNARE LISTBOX IN MODO THREAD-SAFE
# ===============================
def aggiorna_listbox_safe(t, t_val, h_val):  # t=tempo(s), t_val=temperatura(°C), h_val=umidità(%)
    """Aggiorna listbox dati ricevuti usando thread principale Tkinter (thread-safe)"""
    try:
        # Verifica esistenza widget per evitare crash durante chiusura app
        if lista_dati is not None and lista_dati.winfo_exists():  
            # Inserisce nuovo dato in cima (posizione 0) con formato fisso per allineamento
            lista_dati.insert(0, f"T:{t:5.1f}s|T:{t_val:5.1f}°C|U:{h_val:3d}%")  
            # Mantiene lista a max 50 elementi eliminando il più vecchio (ottimizzazione memoria)
            if lista_dati.size() > 50:  
                lista_dati.delete(50, tk.END)  
    except tk.TclError:  # Ignora errori se widget distrutto durante aggiornamento
        pass  


# ===============================
# THREAD DEDICATO LETTURA BLUETOOTH
# ===============================
def bluetooth_reader():  # Thread background continuo per lettura seriale non bloccante
    """Thread dedicato: legge continuamente dati ESP32 senza bloccare interfaccia grafica"""
    global app_in_esecuzione  # Controllo stato app per terminazione pulita
    ser = None  # Handle connessione seriale (None=inattiva)
    tentativi = 0  # Contatore tentativi connessione iniziale
    max_tentativi = 3  # Massimo 3 tentativi prima di arrendersi
    
    # Loop tentativi connessione con backoff esponenziale
    while tentativi < max_tentativi and app_in_esecuzione:  
        try:
            # Apertura porta seriale con timeout 1s per rilevare disconnessioni
            ser = serial.Serial(BT_PORT, BT_BAUD, timeout=1)  
            print("✓ Bluetooth connesso su " + BT_PORT)
            break  # Connessione OK, esci dal loop tentativi
        except Exception as e:  # Gestione errori: porta occupata, ESP32 spento, cavo scollegato
            tentativi += 1
            print(f"✗ Tentativo {tentativi}/{max_tentativi} fallito: {e}")
            time.sleep(2)  # Pausa 2s tra tentativi (evita sovraccarico CPU)
    
    # Se falliscono tutti i tentativi, termina thread senza crash
    if ser is None:  
        print("ERRORE CRITICO: Impossibile connettersi al Bluetooth su " + BT_PORT)
        return  

    # Loop principale acquisizione dati (non bloccante grazie timeout seriale)
    while app_in_esecuzione:  
        try:
            # Lettura riga seriale, decode UTF-8, rimozione spazi bianchi
            line = ser.readline().decode().strip()  
            # Validazione formato ESP32: deve iniziare con "DATA;"
            if not line.startswith("DATA;"):  
                continue  # Ignora righe invalide (rumore, comandi, errori)

            # Parsing dati: "DATA;T=23.5;U=65" → t_val=23.5, h_val=65
            parts = line.split(";")  # Split su separatore ";"
            t_val = float(parts[1].split("=")[1])  # Estrae temperatura dopo "T="
            h_val = int(parts[2].split("=")[1])  # Estrae umidità dopo "U="

            # Processa solo se acquisizione attiva (non in pausa)
            if aggiornamento_attivo:  
                with lock:  # Sezione critica: accesso esclusivo alle liste dati
                    global ignora_prossimo_dato, start_time  # Variabili per gestione pausa

                    # Gestione ripresa dopo pausa: reset temporale corretto
                    if ignora_prossimo_dato:  
                        ignora_prossimo_dato = False  
                        if len(secondi) > 0:  
                            ultimo_tempo = secondi[-1]  # Riprende da ultimo tempo valido
                            start_time = time.time() - ultimo_tempo  # Risincronizza
                    else:
                        # Calcolo tempo relativo dall'inizio acquisizione
                        t = time.time() - start_time  
                        # Append sicuri (liste thread-safe con lock)
                        secondi.append(t)  
                        temperatura.append(t_val)  
                        umidita.append(h_val)  

                    # Aggiornamento interfaccia listbox dal thread principale
                    try:  
                        root.after(0, aggiorna_listbox_safe, t, t_val, h_val)  
                    except:  
                        pass  # Ignora se interfaccia non pronta

                    # Limitazione memoria: max 300 punti (~1-2min a 115200baud)
                    if len(secondi) > 300:  
                        secondi.pop(0)  # Rimuove dato più vecchio (FIFO)
                        temperatura.pop(0)  
                        umidita.pop(0)  
        except Exception as e:  # Gestione disconnessioni improvvise
            if app_in_esecuzione:  
                print(f"Errore thread Bluetooth: {e}")
            time.sleep(0.1)  # Piccola pausa per evitare loop CPU 100%
    
    # Chiusura pulita connessione seriale
    if ser:  
        try:
            ser.close()  
            print("✓ Connessione Bluetooth chiusa correttamente")
        except:
            pass  


# ===============================
# CONFIGURAZIONE TKINTER BASE
# ===============================
INTERVALLO = 250  # Refresh grafico 250ms = 4 FPS (bilanciato fluidità/prestazioni)
BG = "#0f0f0f"  # Tema dark: sfondo nero profondo
BTN_BG = "#ffffff"  # Pulsanti menu bianchi luminosi
BTN_HOVER = "#dddddd"  # Effetto hover: grigio chiaro
TXT = "#ffffff"  # Testi principali bianchi

# Inizializzazione finestra principale
root = tk.Tk()  
root.title("ESP32 Real-Time Monitor v2.0")  # Titolo finestra con versione
root.geometry("1200x550")  # Dimensioni ottimali (larghezza per grafico+lista)
root.minsize(1200, 550)  # Blocca ridimensionamento minimo
root.configure(bg=BG)  # Applica tema dark globale

# Grid responsive: espansione intelligente su ridimensionamento finestra
root.rowconfigure(0, weight=0)  # Header fisso
root.rowconfigure(1, weight=0)  # Status fisso  
root.rowconfigure(2, weight=1)  # Grafico espandibile verticale
root.rowconfigure(3, weight=0)  # Pulsanti fissi
root.rowconfigure(4, weight=0)  # Metriche fisse
root.columnconfigure(0, weight=1)  # Grafico espandibile orizzontale
root.columnconfigure(1, weight=0)  # Lista dati larghezza fissa

status = tk.StringVar(value="Seleziona il tipo di grafico")  # Status bar dinamica


# ===============================
# GESTIONE CHIUSURA SICURA APP
# ===============================
def on_closing():  
    """Protocollo chiusura ordinata: ferma thread, chiude connessioni, distrugge GUI"""
    global aggiornamento_attivo, app_in_esecuzione
    print("Chiusura ordinata applicazione...")
    aggiornamento_attivo = False  # Blocca immediatamente acquisizione/grafico
    app_in_esecuzione = False  # Segnala terminazione a tutti i thread
    time.sleep(0.5)  # Grace period per terminazione pulita thread
    try:
        root.quit()  # Ferma event loop Tkinter
        root.destroy()  # Distrugge finestra e risorse GUI
    except:
        pass  

# Registra gestore evento chiusura finestra (pulsante X)
root.protocol("WM_DELETE_WINDOW", on_closing)  


# ===============================
# CREATORE PULSANTI STILIZZATI
# ===============================
def fancy_button(text, command):  
    """Factory pulsanti moderni: flat design, hover effects, font professionale"""
    # Widget Button con stile Material Design
    b = tk.Button(  
        root,
        text=text,
        font=("Segoe UI", 12, "bold"),  # Font Windows moderno
        bg=BTN_BG,  # Bianco base
        fg="#000000",  # Testo nero contrasto alto
        activebackground=BTN_HOVER,  # Grigio su hover/click
        relief="flat",  # No bordi 3D
        bd=0,  # No bordo
        width=22,  # Larghezza fissa
        height=2,  # Altezza fissa
        command=command,  # Callback click
        cursor="hand2"  # Cursor pointer
    )
    # Effetti hover dinamici (bind eventi mouse)
    b.bind("<Enter>", lambda e: b.config(bg=BTN_HOVER))  # Mouse enter → grigio
    b.bind("<Leave>", lambda e: b.config(bg=BTN_BG))  # Mouse leave → bianco
    return b


# ===============================
# SCHERMATA MENU INIZIALE
# ===============================
def mostra_menu_iniziale():  
    """Interfaccia selezione modalità: pulisce dati e mostra pulsanti scelta"""
    global secondi, umidita, temperatura, aggiornamento_attivo
    # Reset completo sessione: ferma acquisizione e svuota buffer dati
    aggiornamento_attivo = False  
    with lock:  
        secondi = []  # Reset tempo
        umidita = []  # Reset umidità
        temperatura = []  # Reset temperatura

    # Distrugge tutti i widget figli (pulizia totale interfaccia)
    for w in root.winfo_children():  
        w.destroy()  

    # Titolo principale centrato grande
    tk.Label(  
        root,
        text="ESP32 REAL-TIME MONITOR",
        font=("Segoe UI", 18, "bold"),
        bg=BG,
        fg=TXT
    ).pack(pady=(50, 10))  # Padding verticale generoso

    # Sottotitolo esplicativo
    tk.Label(  
        root,
        text="Seleziona il grafico da visualizzare",
        font=("Segoe UI", 11),
        bg=BG,
        fg="#bbbbbb"  # Grigio chiaro secondario
    ).pack(pady=(0, 30))

    # Trio pulsanti modalità (stack verticale centrati)
    fancy_button("UMIDITÀ", lambda: avvia_grafico("umidita")).pack(pady=10)  
    fancy_button("TEMPERATURA", lambda: avvia_grafico("temperatura")).pack(pady=10)  
    fancy_button("UMIDITÀ + TEMPERATURA", lambda: avvia_grafico("entrambe")).pack(pady=10)  


# ===============================
# CALCOLATORE METRICHE REGRESSIONE
# ===============================
def calcola_metriche(y_real, y_pred):  
    """Calcola MSE, RMSE, R² per valutare accuratezza modello rispetto dati reali"""
    try:
        mse = np.mean((y_real - y_pred) ** 2)  # Mean Squared Error (errore quadratico medio)
        rmse = np.sqrt(mse)  # Root Mean Squared Error (radice errore quadratico)
        ss_res = np.sum((y_real - y_pred) ** 2)  # Somma quadrati residui
        ss_tot = np.sum((y_real - np.mean(y_real)) ** 2)  # Somma quadrati totali (varianza)
        r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0  # R² (coefficiente determinazione)
        return mse, rmse, r2
    except Exception as e:
        print(f"Errore calcolo metriche: {e}")
        return 0, 0, 0  # Valori safe in caso errore


# ===============================
# TOGGLE VISIBILITÀ METRICHE
# ===============================
def toggle_metriche():  
    """Alterna visibilità pannello statistiche regressione (espandi/restringi)"""
    global mostra_metriche
    try:
        mostra_metriche = not mostra_metriche  # Toggle booleano
        if mostra_metriche:  
            metriche_label.grid()  # Mostra widget (grid visibile)
        else:  
            metriche_label.grid_remove()  # Nasconde widget (non distrugge)
    except Exception as e:
        print(f"Errore toggle metriche: {e}")


# ===============================
# TOGGLE PAUSA/RIPRESA ACQUISIZIONE
# ===============================
def toggle_aggiornamento():  
    """Alterna STOP/PLAY: pausa/ripresa acquisizione dati e refresh grafico"""
    global aggiornamento_attivo, start_time, ignora_prossimo_dato
    try:
        if aggiornamento_attivo:  # Da PLAY → STOP
            aggiornamento_attivo = False  
            status.set("Aggiornamento fermato")  
            pulsante_stop.config(text="PLAY", bg="#55ff55", fg="#000000")  # Verde PLAY
        else:  # Da STOP → PLAY
            ignora_prossimo_dato = True  # Flag per risincronizzare tempo
            aggiornamento_attivo = True  
            status.set("Aggiornamento attivo")  
            pulsante_stop.config(text="STOP", bg="#ff5555", fg="#ffffff")  # Rosso STOP
            aggiorna_grafico()  # Riavvia ciclo refresh grafico
    except Exception as e:
        print(f"Errore toggle aggiornamento: {e}")


# ===============================
# ESPORTAZIONE GRAFICO + DATI EXCEL
# ===============================
def salva_grafico_e_excel():  
    """Esporta screenshot grafico PNG + dati Excel con fogli separati per modalità"""
    global MODALITA, secondi, umidita, temperatura, fig

    # Controlli di sicurezza pre-salvataggio
    if aggiornamento_attivo:  
        messagebox.showwarning("Pausa richiesta", "Salvataggio solo con grafico in STOP.")
        return
    if len(secondi) < 1:  
        messagebox.showwarning("Nessun dato", "Acquisisci dati prima di salvare.")
        return

    # Dialogo nativo salvataggio con nome base personalizzabile
    file_base = filedialog.asksaveasfilename(  
        defaultextension="",
        filetypes=[("Tutti i file", "*.*")],
        title="Scegli nome base file (senza estensione)"
    )
    if not file_base:  # Annullato dall'utente
        return

    # Salvataggio PNG ad alta risoluzione (150 DPI professionale)
    try:
        fig.savefig(file_base + ".png", dpi=150, bbox_inches='tight')  
        print(f"✓ PNG salvato: {file_base}.png")
    except Exception as e:
        messagebox.showerror("Errore PNG", f"Impossibile salvare immagine:\n{e}")
        return

    # Preparazione dati thread-safe per Excel
    try:
        with lock:  
            t = list(secondi)  # Copia tempi
            u = list(umidita)  # Copia umidità
            temp = list(temperatura)  # Copia temperatura

        # ExcelWriter con motore xlsxwriter (formattazione professionale)
        writer = pd.ExcelWriter(file_base + ".xlsx", engine="xlsxwriter")  

        # Logica esportazione per modalità:
        if MODALITA == "umidita":  
            df_um = pd.DataFrame({"Tempo_s": t, "Umidita_%": u})  
            df_um.to_excel(writer, sheet_name="Umidita", index=False)  

        elif MODALITA == "temperatura":  
            df_t = pd.DataFrame({"Tempo_s": t, "Temperatura_C": temp})  
            df_t.to_excel(writer, sheet_name="Temperatura", index=False)  

        elif MODALITA == "entrambe":  
            # Due fogli distinti nello stesso file Excel
            df_um = pd.DataFrame({"Tempo_s": t, "Umidita_%": u})  
            df_t = pd.DataFrame({"Tempo_s": t, "Temperatura_C": temp})  
            df_um.to_excel(writer, sheet_name="Umidita", index=False)  
            df_t.to_excel(writer, sheet_name="Temperatura", index=False)  

        writer.close()  # Commit e chiusura file Excel
        print(f"✓ Excel salvato: {file_base}.xlsx")

        # Conferma successo con lista file generati
        messagebox.showinfo(  
            "Salvataggio completato!",
            f"File esportati con successo:\n\n{file_base}.png\n{file_base}.xlsx"
        )
    except Exception as e:
        messagebox.showerror("Errore Excel", f"Impossibile salvare dati:\n{e}")


# ===============================
# INIZIALIZZAZIONE INTERFACCIA GRAFICO
# ===============================
def avvia_grafico(mod):  
    """Setup completo interfaccia modalità grafico: GUI + Matplotlib + controlli"""
    global MODALITA, aggiornamento_attivo, fig, ax, canvas, metriche_label, pulsante_stop, start_time, lista_dati

    # Reset sessione: modalità, stato, cronometro
    MODALITA = mod  
    aggiornamento_attivo = True  
    start_time = time.time()  

    # Cleanup interfaccia precedente
    for w in root.winfo_children():  
        w.destroy()  

    # Header titolo modalità attiva
    tk.Label(  
        root,
        text=f"ESP32 REAL-TIME · {MODALITA.upper()}",
        font=("Segoe UI", 16, "bold"),
        bg=BG,
        fg=TXT
    ).grid(row=0, column=0, columnspan=2, pady=(10, 5))

    # Status bar punti acquisiti (dinamica)
    tk.Label(  
        root,
        textvariable=status,
        font=("Segoe UI", 10),
        bg=BG,
        fg="#aaaaaa"
    ).grid(row=1, column=0, columnspan=2, pady=5)

    # Frame contenitore grafico principale (espandibile)
    frame_grafico = tk.Frame(root, bg=BG)  
    frame_grafico.grid(row=2, column=0, sticky="nsew", padx=10, pady=5)  

    # Frame lista dati live (destra, fisso)
    frame_lista = tk.Frame(root, bg=BG)  
    frame_lista.grid(row=2, column=1, sticky="nsew", padx=(0, 10), pady=5)  

    # Header lista dati
    tk.Label(  
        frame_lista,
        text="DATI RICEVUTI (LIVE)",
        font=("Segoe UI", 10, "bold"),
        bg=BG,
        fg=TXT
    ).pack(pady=(0, 5))

    # Scrollbar verticale listbox
    scrollbar = tk.Scrollbar(frame_lista, bg=BG)  
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)  

    # Listbox dati live (monospace, colori cyberpunk)
    lista_dati = tk.Listbox(  
        frame_lista,
        width=28,  # Larghezza fissa colonne allineate
        height=20,
        font=("Consolas", 9),  # Monospace per allineamento perfetto
        bg="#1a1a1a",  # Sfondo grigio scuro
        fg="#00ff88",  # Verde neon dati
        selectbackground="#333333",
        yscrollcommand=scrollbar.set  
    )
    lista_dati.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.config(command=lista_dati.yview)  

    # Barra controlli inferiore
    frame_pulsante = tk.Frame(root, bg=BG)  
    frame_pulsante.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=10)  

    # Pannello metriche nascoste (row 4)
    metriche_label = tk.Label(  
        root,
        text="Statistiche regressione caricate automaticamente...",
        font=("Courier", 11, "bold"),
        bg="#111111",  # Sfondo nero opaco
        fg="#00ff88",  # Verde neon metriche
        justify="left",
        anchor="w"
    )
    metriche_label.grid(row=4, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 10))
    metriche_label.grid_remove()  # Inizialmente nascoste

    # Setup Matplotlib tema dark + figura professionale
    plt.style.use("dark_background")  
    fig, ax = plt.subplots(figsize=(8, 4), dpi=120)  # 8x4 pollici, 120 DPI
    fig.subplots_adjust(left=0.15, right=0.95, top=0.9, bottom=0.15)  # Margini ottimizzati

    # Integrazione canvas Matplotlib → Tkinter
    canvas = FigureCanvasTkAgg(fig, master=frame_grafico)  
    canvas.get_tk_widget().pack(fill="both", expand=True)  

    # Pulsante INDIETRO (blu)
    tk.Button(  
        frame_pulsante,
        text="← INDIETRO",
        font=("Segoe UI", 12, "bold"),
        bg="#5555ff",  # Blu primario
        fg="#ffffff",
        relief="flat",
        bd=0,
        width=12,
        height=1,
        cursor="hand2",
        command=lambda: mostra_menu_iniziale()
    ).pack(side="left", padx=(0, 10))

    # Pulsante STOP/PLAY dinamico (rosso/verde)
    pulsante_stop = tk.Button(  
        frame_pulsante,
        text="STOP",  # Stato iniziale
        font=("Segoe UI", 12, "bold"),
        bg="#ff5555",  # Rosso stop
        fg="#ffffff",
        relief="flat",
        bd=0,
        width=12,
        height=1,
        cursor="hand2",
        command=toggle_aggiornamento
    )
    pulsante_stop.pack(side="left", padx=(0, 10))

    # Pulsante DETTAGLI metriche (verde)
    tk.Button(  
        frame_pulsante,
        text="DETTAGLI",
        font=("Segoe UI", 12, "bold"),
        bg="#55ff55",  # Verde info
        fg="#000000",
        relief="flat",
        bd=0,
        width=12,
        height=1,
        cursor="hand2",
        command=toggle_metriche
    ).pack(side="left")

    # Pulsante SALVA (arancione)
    tk.Button(  
        frame_pulsante,
        text="Salva PNG + Excel",
        font=("Segoe UI", 12, "bold"),
        bg="#ffaa00",  # Arancione salvataggio
        fg="#000000",
        relief="flat",
        bd=0,
        width=16,
        height=1,
        cursor="hand2",
        command=salva_grafico_e_excel
    ).pack(side="left", padx=(10, 0))

    # Avvio primo ciclo grafico
    aggiorna_grafico()  


# ===============================
# LOOP RENDERING GRAFICO REALTIME
# ===============================
def aggiorna_grafico():  
    """Ciclo principale rendering: regressioni lineari/quadatiche + metriche live"""
    # Early exit se app chiusa o in pausa
    if not aggiornamento_attivo or not app_in_esecuzione:  
        return

    try:
        with lock:  # Accesso atomico dati condivisi
            # Controllo dati minimi per regressione (2+ punti)
            if len(secondi) < 2:  
                root.after(INTERVALLO, aggiorna_grafico)  
                return

            # Conversione liste → array NumPy per calcoli vettoriali veloci
            X = np.array(secondi)  

            # Selezione dati per modalità attiva
            if MODALITA == "umidita":  
                Y = np.array(umidita)  
            elif MODALITA == "temperatura":  
                Y = np.array(temperatura)  
            else:  # "entrambe"
                Y_um = np.array(umidita)  
                Y_temp = np.array(temperatura)

        # Reset asse grafico (pulizia frame precedente)
        ax.clear()  
        ax.grid(True, alpha=0.3)  # Griglia leggera professionale
        ax.set_xlabel("Tempo (s)", fontsize=10)  
        
        # Etichette Y dinamiche per modalità
        ax.set_ylabel(  
            "Umidità (%)" if MODALITA == "umidita" else
            "Temperatura (°C)" if MODALITA == "temperatura" else
            "Valore",
            fontsize=10
        )

        # Formattazione assi con 1 decimale (precisione scientifica)
        from matplotlib.ticker import FormatStrFormatter  
        ax.yaxis.set_major_formatter(FormatStrFormatter('%.1f'))  
        ax.xaxis.set_major_formatter(FormatStrFormatter('%.1f'))  

        # === GRAFICO SINGOLO (UMIDITÀ o TEMPERATURA) ===
        if MODALITA in ["umidita", "temperatura"]:  
            # Scatter plot dati live (cyan umidità, lime temperatura)
            ax.scatter(X, Y, color="cyan" if MODALITA == "umidita" else "lime", label="Dati", s=20)  

            # Regressione lineare 1° grado (retta)
            coeff_ang, intercetta = np.polyfit(X, Y, 1)  
            Y_pred = coeff_ang * X + intercetta  
            ax.plot(X, Y_pred, "--", color="orange", label="Retta", linewidth=2)  

            # Regressione quadratica 2° grado (parabola, min 3 punti)
            if len(X) >= 3:  
                a, b, c = np.polyfit(X, Y, 2)  
                xp = np.linspace(X.min(), X.max(), 200)  # 200 punti per curva fluida
                Y_parabola = a * xp**2 + b * xp + c  
                ax.plot(xp, Y_parabola, "-.", color="magenta", label="Parabola", linewidth=2)  

            # Metriche retta di riferimento
            mse, rmse, r2 = calcola_metriche(Y, Y_pred)  

            # Aggiornamento pannello metriche (se visibile)
            if mostra_metriche:  
                testo_metriche = f"=== RETTA LINEARE ===\n"
                testo_metriche += f"Equazione: y = {coeff_ang:.2f}x + {intercetta:.2f}\n"
                testo_metriche += f"MSE: {mse:.2f} | RMSE: {rmse:.2f} | R²: {r2:.4f}\n"

                if len(X) >= 3:  
                    # Metriche parabola
                    Y_pred_parabola = a * X**2 + b * X + c  
                    mse_par, rmse_par, r2_par = calcola_metriche(Y, Y_pred_parabola)  
                    testo_metriche += f"\n=== PARABOLA QUADRATICA ===\n"
                    testo_metriche += f"Equazione: y = {a:.4f}x² + {b:.2f}x + {c:.2f}\n"
                    testo_metriche += f"MSE: {mse_par:.2f} | RMSE: {rmse_par:.2f} | R²: {r2_par:.4f}"

                metriche_label.config(text=testo_metriche)  

            ax.legend(loc='best')  # Legenda automatica posizione ottimale

        # === GRAFICO DOPPIO (UMIDITÀ + TEMPERATURA) ===
        else:  
            # Scatter entrambi dataset
            ax.scatter(X, Y_um, color="cyan", label="Dati Umidità", s=20)  
            ax.scatter(X, Y_temp, color="lime", label="Dati Temperatura", s=20)  

            # Retta umidità
            coeff_ang_um, intercetta_um = np.polyfit(X, Y_um, 1)  
            ax.plot(X, coeff_ang_um * X + intercetta_um, "--", color="cyan", alpha=0.7, label="Retta Umidità", linewidth=2)  

            # Retta temperatura
            coeff_ang_temp, intercetta_temp = np.polyfit(X, Y_temp, 1)  
            ax.plot(X, coeff_ang_temp * X + intercetta_temp, "--", color="lime", alpha=0.7, label="Retta Temperatura", linewidth=2)  

            # Metriche rette
            Y_pred_um_retta = coeff_ang_um * X + intercetta_um
            Y_pred_temp_retta = coeff_ang_temp * X + intercetta_temp
            mse_um_r, rmse_um_r, r2_um_r = calcola_metriche(Y_um, Y_pred_um_retta)
            mse_temp_r, rmse_temp_r, r2_temp_r = calcola_metriche(Y_temp, Y_pred_temp_retta)

            # Parabole (min 3 punti)
            if len(X) >= 3:  
                xp = np.linspace(X.min(), X.max(), 200)  
                
                # Parabola umidità
                a_um, b_um, c_um = np.polyfit(X, Y_um, 2)  
                ax.plot(xp, a_um * xp**2 + b_um * xp + c_um, "-.", color="cyan", alpha=0.5, label="Parabola Umidità", linewidth=2)  

                # Parabola temperatura
                a_temp, b_temp, c_temp = np.polyfit(X, Y_temp, 2)  
                ax.plot(xp, a_temp * xp**2 + b_temp * xp + c_temp, "-.", color="lime", alpha=0.5, label="Parabola Temp", linewidth=2)  

                # Metriche parabole
                Y_pred_um_parabola = a_um * X**2 + b_um * X + c_um
                Y_pred_temp_parabola = a_temp * X**2 + b_temp * X + c_temp
                mse_um_p, rmse_um_p, r2_um_p = calcola_metriche(Y_um, Y_pred_um_parabola)
                mse_temp_p, rmse_temp_p, r2_temp_p = calcola_metriche(Y_temp, Y_pred_temp_parabola)

            # === PANELLO METRICHE COMPLETO (UMIDITÀ + TEMPERATURA) ===
            if mostra_metriche:  
                testo_metriche = "═══ UMIDITÀ ═══\n"
                testo_metriche += f"RETTA: y={coeff_ang_um:.2f}x+{intercetta_um:.2f}\n"
                testo_metriche += f"  MSE:{mse_um_r:6.2f}  RMSE:{rmse_um_r:5.2f}  R²:{r2_um_r:.4f}\n"
                
                if len(X) >= 3:
                    testo_metriche += f"PARABOLA: y={a_um:.4f}x²+{b_um:.2f}x+{c_um:.2f}\n"
                    testo_metriche += f"  MSE:{mse_um_p:6.2f}  RMSE:{rmse_um_p:5.2f}  R²:{r2_um_p:.4f}\n"
                
                testo_metriche += "\n═══ TEMPERATURA ═══\n"
                testo_metriche += f"RETTA: y={coeff_ang_temp:.2f}x+{intercetta_temp:.2f}\n"
                testo_metriche += f"  MSE:{mse_temp_r:6.2f}  RMSE:{rmse_temp_r:5.2f}  R²:{r2_temp_r:.4f}\n"
                
                if len(X) >= 3:
                    testo_metriche += f"PARABOLA: y={a_temp:.4f}x²+{b_temp:.2f}x+{c_temp:.2f}\n"
                    testo_metriche += f"  MSE:{mse_temp_p:6.2f}  RMSE:{rmse_temp_p:5.2f}  R²:{r2_temp_p:.4f}"
                
                metriche_label.config(text=testo_metriche)  

            ax.legend(loc='best')  

        # Auto-scaling X per focus su dati recenti (+0.5s padding)
        ax.set_xlim(X.min(), X.max() + 0.5)  
        fig.tight_layout()  # Layout automatico margini
        
        # Refresh canvas solo se widget esiste
        if canvas and canvas.get_tk_widget().winfo_exists():  
            canvas.draw_idle()  

        # Aggiornamento status bar
        status.set(f"Punti acquisiti: {len(X)} | Modalità: {MODALITA}")

    except Exception as e:
        print(f"Errore rendering grafico: {e}")
        return

    # Scheduling prossimo frame (loop infinito 250ms)
    if app_in_esecuzione and aggiornamento_attivo:  
        root.after(INTERVALLO, aggiorna_grafico)  


# ===============================
# AVVIO THREAD BACKGROUND
# ===============================
# Lancio thread Bluetooth daemon (termina automaticamente con app principale)
print("Avvio ESP32 Real-Time Monitor...")
threading.Thread(target=bluetooth_reader, daemon=True).start()  


# ===============================
# EVENT LOOP PRINCIPALE
# ===============================
mostra_menu_iniziale()  # Schermata iniziale
root.mainloop()  # Avvio ciclo eventi Tkinter (bloccante)