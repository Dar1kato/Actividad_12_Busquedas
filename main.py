"""
main.py
=======
Evaluación de algoritmos de búsqueda informada en grafos (Voraz y A*)
dentro de una arquitectura backend con FastAPI.

Ejecución (proyecto creado con `uv init`):
    uv add fastapi uvicorn httpx
    uv run uvicorn main:app --reload      # levanta la API
    uv run python main.py                 # corre las 18 pruebas (9 por endpoint)

Secciones del archivo:
    1. Esquemas Pydantic (entrada / salida)
    2. Utilidades comunes (heurística euclidiana, coordenadas, ruta)
    3. Módulo "greedy_search"  -> búsqueda voraz
    4. Módulo "star_search"    -> búsqueda A*
    5. Endpoints FastAPI
    6. Grafos de prueba y escenarios de evaluación
"""

import heapq
import itertools
import math
import time
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple, Union

from fastapi import Body, FastAPI
from pydantic import BaseModel, Field, PrivateAttr, model_validator

# Tipo interno del grafo: {nodo: {vecino: peso}}
Adyacencia = Dict[str, Dict[str, float]]
Coordenadas = Dict[str, Tuple[float, float]]


# =============================================================================
# 1. ESQUEMAS PYDANTIC
# =============================================================================
class EntradaBusqueda(BaseModel):
    """
    Esquema de validación de la entrada.

    `grafo` acepta dos representaciones:
      * Lista de adyacencia con pesos:  {"A": [["B", 15], ["C", 22]], "B": [], ...}
      * Matriz de adyacencia con pesos: [[0, 15, 22], [0, 0, 0], ...]
        (0 = sin arista). En este caso `nodos` da las etiquetas; si se omite,
        se usan "0", "1", "2", ...

    `coordenadas` (opcional) = posición (x, y) de cada nodo para la heurística
    euclidiana. Si no se envían, se generan de forma determinística.

    `limite_nodos` = máximo de nodos a visitar (por defecto, 80 % del total).
    """

    grafo: Union[Dict[str, List[Tuple[str, float]]], List[List[float]]]
    nodos: Optional[List[str]] = None
    coordenadas: Optional[Coordenadas] = None
    origen: str
    destino: str
    limite_nodos: Optional[int] = Field(default=None, ge=1)

    _adj: Adyacencia = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def validar_y_normalizar(self) -> "EntradaBusqueda":
        adj: Adyacencia = {}

        if isinstance(self.grafo, dict):
            if not self.grafo:
                raise ValueError("El grafo no puede estar vacío.")
            for u in self.grafo:
                adj[u] = {}
            for u, vecinos in self.grafo.items():
                for v, w in vecinos:
                    if v not in adj:
                        raise ValueError(f"La arista {u}->{v} apunta a un nodo inexistente.")
                    if w <= 0:
                        raise ValueError(f"Peso inválido en {u}->{v}: debe ser > 0.")
                    # Si hay aristas paralelas, se conserva la de menor peso.
                    adj[u][v] = min(w, adj[u].get(v, math.inf))
        else:
            n = len(self.grafo)
            if n == 0 or any(len(fila) != n for fila in self.grafo):
                raise ValueError("La matriz de adyacencia debe ser cuadrada y no vacía.")
            etiquetas = self.nodos or [str(i) for i in range(n)]
            if len(etiquetas) != n or len(set(etiquetas)) != n:
                raise ValueError("`nodos` debe tener n etiquetas únicas.")
            for u in etiquetas:
                adj[u] = {}
            for i, fila in enumerate(self.grafo):
                for j, w in enumerate(fila):
                    if w < 0:
                        raise ValueError(f"Peso negativo en la posición [{i}][{j}].")
                    if w > 0:
                        adj[etiquetas[i]][etiquetas[j]] = w

        if self.origen not in adj:
            raise ValueError(f"El origen '{self.origen}' no existe en el grafo.")
        if self.destino not in adj:
            raise ValueError(f"El destino '{self.destino}' no existe en el grafo.")

        if self.coordenadas is not None:
            faltantes = [n for n in adj if n not in self.coordenadas]
            if faltantes:
                raise ValueError(f"Faltan coordenadas para los nodos: {faltantes}")

        # Límite por defecto: 80 % del total de nodos (redondeado hacia arriba).
        if self.limite_nodos is None:
            self.limite_nodos = math.ceil(0.8 * len(adj))

        self._adj = adj
        return self

    @property
    def adyacencia(self) -> Adyacencia:
        return self._adj


class Complejidad(BaseModel):
    medido: Dict[str, Union[int, float]]
    teorico: str


class SalidaBusqueda(BaseModel):
    nodos_visitados: int
    solucion: bool
    ruta: List[str]
    costo_ruta: Optional[float] = None
    T_n: Complejidad
    S_n: Complejidad


# =============================================================================
# 2. UTILIDADES COMUNES
# =============================================================================
def distancia_euclidiana(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def generar_coordenadas(adj: Adyacencia) -> Coordenadas:
    """
    Genera coordenadas determinísticas cuando el cliente no las envía.

    Disposición por capas: x = saltos mínimos desde los nodos sin aristas
    entrantes, y = posición dentro de la capa. Luego se escala todo por
    min(peso / distancia) sobre las aristas, de modo que la distancia
    euclidiana nunca supere el peso de una arista. Eso hace que h(n) sea
    admisible y consistente, y A* conserve su optimalidad.
    """
    nodos = list(adj)
    entrantes = {n: 0 for n in nodos}
    for u in adj:
        for v in adj[u]:
            entrantes[v] += 1

    fuentes = [n for n in nodos if entrantes[n] == 0] or nodos[:1]
    nivel: Dict[str, int] = {}
    cola = deque()
    for s in fuentes:
        nivel[s] = 0
        cola.append(s)
    while cola:
        u = cola.popleft()
        for v in adj[u]:
            if v not in nivel:
                nivel[v] = nivel[u] + 1
                cola.append(v)
    for n in nodos:
        nivel.setdefault(n, 0)

    ocupados: Dict[int, int] = defaultdict(int)
    base: Coordenadas = {}
    for n in nodos:
        k = ocupados[nivel[n]]
        ocupados[nivel[n]] += 1
        base[n] = (float(nivel[n]), float(k))

    factor = math.inf
    for u in adj:
        for v, w in adj[u].items():
            d = distancia_euclidiana(base[u], base[v])
            if d > 0:
                factor = min(factor, w / d)
    if factor == math.inf:
        factor = 1.0

    return {n: (x * factor, y * factor) for n, (x, y) in base.items()}


def reconstruir_ruta(padre: Dict[str, Optional[str]], destino: str) -> List[str]:
    ruta, actual = [], destino
    while actual is not None:
        ruta.append(actual)
        actual = padre[actual]
    return ruta[::-1]


def costo_de_ruta(adj: Adyacencia, ruta: List[str]) -> float:
    return sum(adj[u][v] for u, v in zip(ruta, ruta[1:]))


def armar_resultado(
    adj: Adyacencia,
    padre: Dict[str, Optional[str]],
    destino: str,
    encontrado: bool,
    visitados: int,
    operaciones: int,
    max_frontera: int,
    max_memoria: int,
    t0: float,
    t_teorico: str,
    s_teorico: str,
) -> dict:
    ruta = reconstruir_ruta(padre, destino) if encontrado else []
    return {
        "nodos_visitados": visitados,
        "solucion": encontrado,
        "ruta": ruta,
        "costo_ruta": costo_de_ruta(adj, ruta) if encontrado else None,
        "T_n": {
            "medido": {
                "operaciones": operaciones,
                "tiempo_ms": round((time.perf_counter() - t0) * 1000, 4),
            },
            "teorico": t_teorico,
        },
        "S_n": {
            "medido": {
                "max_frontera": max_frontera,
                "max_nodos_en_memoria": max_memoria,
            },
            "teorico": s_teorico,
        },
    }


# =============================================================================
# 3. MÓDULO greedy_search  (Búsqueda voraz / Greedy Best-First Search)
# =============================================================================
def greedy_search(
    adj: Adyacencia,
    coords: Coordenadas,
    origen: str,
    destino: str,
    limite_nodos: int,
) -> dict:
    """
    Criterio de selección: f(n) = h(n), con h(n) = distancia euclidiana de n al
    destino. Se expande siempre el nodo de la frontera con menor h(n); los
    empates se resuelven por orden de descubrimiento. Ignora el costo
    acumulado g(n), por eso no garantiza la ruta óptima.

    Conteo de operaciones (T(n) medido): extracciones + inserciones en la
    frontera + aristas evaluadas.
    """
    t0 = time.perf_counter()

    def h(n: str) -> float:
        return distancia_euclidiana(coords[n], coords[destino])

    orden = itertools.count()
    frontera: List[Tuple[float, int, str]] = [(h(origen), next(orden), origen)]
    padre: Dict[str, Optional[str]] = {origen: None}  # también marca "descubiertos"
    cerrados = set()
    operaciones = 1
    max_frontera, max_memoria = 1, 1
    encontrado = False

    while frontera:
        if len(cerrados) >= limite_nodos:  # límite de nodos a visitar
            break
        _, _, actual = heapq.heappop(frontera)
        operaciones += 1
        cerrados.add(actual)

        if actual == destino:
            encontrado = True
            break

        for vecino, _peso in adj[actual].items():
            operaciones += 1
            if vecino not in padre:  # cada nodo entra una sola vez
                padre[vecino] = actual
                heapq.heappush(frontera, (h(vecino), next(orden), vecino))
                operaciones += 1

        max_frontera = max(max_frontera, len(frontera))
        max_memoria = max(max_memoria, len(frontera) + len(cerrados))

    return armar_resultado(
        adj, padre, destino, encontrado, len(cerrados), operaciones,
        max_frontera, max_memoria, t0,
        t_teorico="O(b^m)", s_teorico="O(b^m)",
    )


# =============================================================================
# 4. MÓDULO star_search  (Búsqueda A*)
# =============================================================================
def star_search(
    adj: Adyacencia,
    coords: Coordenadas,
    origen: str,
    destino: str,
    limite_nodos: int,
) -> dict:
    """
    Función de valor: f(n) = g(n) + h(n)
        g(n) = costo acumulado conocido desde el origen hasta n
        h(n) = distancia euclidiana de n al destino

    Usa una cola de prioridad con eliminación perezosa de entradas obsoletas
    (si un nodo mejora su g, se inserta de nuevo y la entrada vieja se ignora
    al extraerla). Con h admisible y consistente, la primera vez que se extrae
    el destino la ruta es óptima.
    """
    t0 = time.perf_counter()

    def h(n: str) -> float:
        return distancia_euclidiana(coords[n], coords[destino])

    orden = itertools.count()
    g: Dict[str, float] = {origen: 0.0}
    frontera: List[Tuple[float, int, str]] = [(h(origen), next(orden), origen)]
    padre: Dict[str, Optional[str]] = {origen: None}
    cerrados = set()
    operaciones = 1
    max_frontera, max_memoria = 1, 1
    encontrado = False

    while frontera:
        if len(cerrados) >= limite_nodos:  # límite de nodos a visitar
            break
        _, _, actual = heapq.heappop(frontera)
        operaciones += 1
        if actual in cerrados:  # entrada obsoleta
            continue
        cerrados.add(actual)

        if actual == destino:
            encontrado = True
            break

        for vecino, peso in adj[actual].items():
            operaciones += 1
            if vecino in cerrados:
                continue
            nuevo_g = g[actual] + peso
            if nuevo_g < g.get(vecino, math.inf):
                g[vecino] = nuevo_g
                padre[vecino] = actual
                heapq.heappush(frontera, (nuevo_g + h(vecino), next(orden), vecino))
                operaciones += 1

        max_frontera = max(max_frontera, len(frontera))
        max_memoria = max(max_memoria, len(frontera) + len(cerrados))

    return armar_resultado(
        adj, padre, destino, encontrado, len(cerrados), operaciones,
        max_frontera, max_memoria, t0,
        t_teorico="O(b^d)", s_teorico="O(b^d)",
    )


# =============================================================================
# 5. GRAFOS DE PRUEBA Y EJEMPLOS PARA /docs
# =============================================================================
GRAFOS = {
    "grafo-10": {
        "A": [["B", 15], ["C", 22], ["D", 10]], "B": [["E", 35], ["F", 18]],
        "C": [["E", 20], ["G", 45]], "D": [["F", 28], ["G", 30]],
        "E": [["H", 12], ["I", 25]], "F": [["H", 40], ["I", 15]],
        "G": [["I", 10], ["J", 50]], "H": [["J", 14]], "I": [["J", 8]], "J": [],
    },
    "grafo-25": {
        "A": [["B", 40], ["D", 36]], "B": [["D", 12], ["G", 30]],
        "C": [["I", 69], ["J", 34]], "D": [["E", 12], ["F", 25], ["I", 22]],
        "E": [["C", 34], ["I", 5]], "F": [["H", 25], ["K", 10], ["M", 32]],
        "G": [["F", 32], ["H", 20], ["K", 15]], "H": [["N", 53], ["K", 20]],
        "I": [["M", 17], ["O", 34]], "J": [["M", 10], ["L", 14]],
        "K": [["N", 24], ["S", 34], ["R", 9]], "L": [["Q", 14]],
        "M": [["R", 32], ["P", 45]], "N": [["T", 52], ["S", 12]],
        "O": [["P", 45], ["L", 12]], "P": [["X", 59]],
        "Q": [["R", 28], ["X", 79]], "R": [["T", 64], ["V", 28], ["U", 16]],
        "S": [["V", 85]], "T": [["W", 72]], "U": [["Y", 19]], "V": [["Y", 19]],
        "W": [["Y", 25]], "X": [["Y", 38]], "Y": [],
    },
    "grafo-50": {
        "A": [["B", 45], ["F", 28], ["C", 60]], "B": [["H", 52], ["I", 30]],
        "C": [["K", 38], ["M", 42]], "D": [["L", 18], ["J", 65]],
        "E": [["O", 22], ["L", 50]], "F": [["K", 35], ["G", 15]],
        "G": [["N", 40]], "H": [["S", 28]], "I": [["S", 33]], "J": [["X", 62]],
        "K": [["R", 24]], "L": [["U", 41]], "M": [["V", 29]], "N": [["W", 19]],
        "O": [["P", 31]], "P": [["AC", 55]], "Q": [["AE", 37]], "R": [["AD", 26]],
        "S": [["AA", 48]], "T": [["Y", 20]], "U": [["AG", 68]], "V": [["AF", 34]],
        "W": [["AA", 15]], "X": [["AG", 42]], "Y": [["AJ", 50]], "Z": [["AH", 39]],
        "AA": [["AM", 30]], "AB": [["AO", 22]], "AC": [["AN", 45]],
        "AD": [["AM", 28]], "AE": [["AK", 51]], "AF": [["AL", 19]],
        "AG": [["AH", 33]], "AH": [["AS", 60]], "AI": [["AT", 25]],
        "AJ": [["AR", 40]], "AK": [["AP", 35]], "AL": [["AU", 28]],
        "AM": [["AV", 18]], "AN": [["AU", 22]], "AO": [["AW", 31]],
        "AP": [["AX", 20]], "AQ": [["AX", 15]], "AR": [["AX", 25]],
        "AS": [["AX", 45]], "AT": [["AX", 18]], "AU": [["AX", 12]],
        "AV": [["AX", 22]], "AW": [["AX", 30]], "AX": [],
    },
}

# 3 pruebas por grafo: (origen, destino) distintos entre sí.
ESCENARIOS = {
    "grafo-10": [("A", "J"), ("C", "I"), ("D", "H")],
    "grafo-25": [("A", "Y"), ("B", "X"), ("C", "T")],
    "grafo-50": [("A", "AX"), ("E", "AC"), ("D", "AH")],
}



# =============================================================================
# 6. ENDPOINTS FASTAPI
# =============================================================================
app = FastAPI(title="Búsqueda informada en grafos: Voraz y A*")

# Ejemplos que aparecen como menú desplegable en /docs -> "Try it out".
EJEMPLOS_DOCS = {
    "grafo-10 (A → J)": {
        "summary": "Grafo de 10 nodos, A → J",
        "value": {"grafo": GRAFOS["grafo-10"], "origen": "A", "destino": "J"},
    },
    "grafo-25 (A → Y)": {
        "summary": "Grafo de 25 nodos, A → Y",
        "value": {"grafo": GRAFOS["grafo-25"], "origen": "A", "destino": "Y"},
    },
    "grafo-50 (A → AX)": {
        "summary": "Grafo de 50 nodos, A → AX",
        "value": {"grafo": GRAFOS["grafo-50"], "origen": "A", "destino": "AX"},
    },
    "matriz (4 nodos, límite manual)": {
        "summary": "Matriz de adyacencia con pesos y límite_nodos explícito",
        "value": {
            "grafo": [[0, 5, 9, 0], [0, 0, 3, 8], [0, 0, 0, 4], [0, 0, 0, 0]],
            "nodos": ["A", "B", "C", "D"],
            "origen": "A",
            "destino": "D",
            "limite_nodos": 4,
        },
    },
}


def _coordenadas_de(entrada: EntradaBusqueda) -> Coordenadas:
    return entrada.coordenadas or generar_coordenadas(entrada.adyacencia)


@app.post("/search/greedy", response_model=SalidaBusqueda)
def buscar_greedy(entrada: EntradaBusqueda = Body(openapi_examples=EJEMPLOS_DOCS)):
    return greedy_search(
        entrada.adyacencia, _coordenadas_de(entrada),
        entrada.origen, entrada.destino, entrada.limite_nodos,
    )


@app.post("/search/star", response_model=SalidaBusqueda)
def buscar_star(entrada: EntradaBusqueda = Body(openapi_examples=EJEMPLOS_DOCS)):
    return star_search(
        entrada.adyacencia, _coordenadas_de(entrada),
        entrada.origen, entrada.destino, entrada.limite_nodos,
    )


# =============================================================================
# 7. ESCENARIOS DE EVALUACIÓN
# =============================================================================
def ejecutar_pruebas() -> None:
    from fastapi.testclient import TestClient  # requiere httpx

    cliente = TestClient(app)
    encabezado = (
        f"{'Grafo':<9}{'Algor.':<8}{'Orig→Dest':<10}{'Lím':<5}{'Visit.':<7}"
        f"{'Sol.':<7}{'Costo':<8}{'Ops':<6}{'ms':<9}{'Frontera':<9}Ruta"
    )
    print(encabezado)
    print("-" * 110)

    for nombre, grafo in GRAFOS.items():
        for origen, destino in ESCENARIOS[nombre]:
            payload = {"grafo": grafo, "origen": origen, "destino": destino}
            for algoritmo, ruta_api in (("Voraz", "/search/greedy"), ("A*", "/search/star")):
                resp = cliente.post(ruta_api, json=payload)
                assert resp.status_code == 200, resp.text
                r = resp.json()
                limite = math.ceil(0.8 * len(grafo))
                print(
                    f"{nombre:<9}{algoritmo:<8}{origen + '→' + destino:<10}{limite:<5}"
                    f"{r['nodos_visitados']:<7}{str(r['solucion']):<7}"
                    f"{str(r['costo_ruta']):<8}{r['T_n']['medido']['operaciones']:<6}"
                    f"{r['T_n']['medido']['tiempo_ms']:<9}"
                    f"{r['S_n']['medido']['max_frontera']:<9}{' → '.join(r['ruta'])}"
                )
        print()

    # Ejemplo de la salida JSON completa de un endpoint
    import json
    ejemplo = cliente.post(
        "/search/star",
        json={"grafo": GRAFOS["grafo-10"], "origen": "A", "destino": "J"},
    ).json()
    print("Ejemplo de respuesta JSON (POST /search/star, grafo-10, A→J):")
    print(json.dumps(ejemplo, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    ejecutar_pruebas()
