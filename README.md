# Actividad 12. Algoritmos de búsqueda informada (heurísticos)

**Daniel Peña Cruz** — 200818

API backend con **FastAPI** que evalúa dos algoritmos de búsqueda informada sobre grafos dirigidos y ponderados: **búsqueda voraz (Greedy Best-First Search)** y **A\***. Ambos están implementados desde cero (solo biblioteca estándar: `heapq`, `math`, `time`, `itertools`, `collections`), sin librerías que ya traigan estos algoritmos. Todo el código vive en un único archivo: `main.py`.

---

## Instalación

Requisitos: [uv](https://docs.astral.sh/uv/) instalado (el gestor instala/usa el Python adecuado).

```bash
# 1. Crear la carpeta del proyecto
uv init actividad-12
cd actividad-12

# 2. Colocar en esta carpeta main.py, run.sh y README.md
#    (reemplaza el main.py que genera `uv init`)

# 3. Instalar dependencias
uv add fastapi uvicorn httpx
```

| Paquete   | Para qué se usa                                              |
|-----------|--------------------------------------------------------------|
| `fastapi` | Framework de la API (incluye Pydantic v2 para los esquemas). |
| `uvicorn` | Servidor ASGI que ejecuta la API.                            |
| `httpx`   | Requerido por el `TestClient` de FastAPI (solo para pruebas).|

Si el proyecto ya tiene su `pyproject.toml` con las dependencias, basta con `uv sync`.

---

## Ejecución

### Método principal: `run.sh`

El archivo `run.sh` contiene el comando de ejecución con uv:

```bash
#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
uv run uvicorn main:app --reload
```

Dale permisos de ejecución la primera vez y lánzalo:

```bash
chmod +x run.sh
./run.sh
```

### Método secundario: comando completo

Equivale a lo anterior, ejecutado directamente desde la carpeta del proyecto:

```bash
uv run uvicorn main:app --reload
```

### Probar la API

Con el servidor levantado:

| URL                              | Descripción                                    |
|----------------------------------|------------------------------------------------|
| `http://127.0.0.1:8000/docs`     | Swagger UI para probar los endpoints.          |
| `http://127.0.0.1:8000/redoc`    | Documentación alternativa (ReDoc).             |
| `http://127.0.0.1:8000/openapi.json` | Esquema OpenAPI.                           |

En `/docs`, abre `POST /search/greedy` o `POST /search/star` → **Try it out**. El cuerpo de la petición tiene un menú desplegable con ejemplos listos (grafos de 10, 25 y 50 nodos, y uno en formato matriz). Elige uno y pulsa **Execute**.

### Correr las 18 pruebas de evaluación

```bash
uv run python main.py
```

Ejecuta 3 escenarios por grafo (10, 25 y 50 nodos) en ambos endpoints y muestra una tabla comparativa, más un ejemplo de respuesta JSON completa.

---

## Cómo funciona el código

`main.py` está dividido en secciones:

| Sección | Contenido |
|---------|-----------|
| 1. Esquemas Pydantic | Validación de entrada (`EntradaBusqueda`) y formato de salida (`SalidaBusqueda`). |
| 2. Utilidades comunes | Distancia euclidiana, generación de coordenadas, reconstrucción de ruta, armado del resultado. |
| 3. `greedy_search` | Búsqueda voraz. |
| 4. `star_search` | Búsqueda A\*. |
| 5. Grafos de prueba | Los grafos de 10, 25 y 50 nodos y los ejemplos para `/docs`. |
| 6. Endpoints | `POST /search/greedy` y `POST /search/star`. |
| 7. Escenarios | Las 9 pruebas por algoritmo y la función `ejecutar_pruebas()`. |

> Los módulos `greedy_search.py` y `star_search.py` pedidos en la actividad se implementan como secciones y funciones independientes dentro de `main.py`, porque el entregable debía ser un solo archivo.

### Esquema de entrada (`EntradaBusqueda`)

| Campo          | Tipo                  | Obligatorio | Descripción |
|----------------|-----------------------|:-----------:|-------------|
| `grafo`        | lista de adyacencia **o** matriz de adyacencia | Sí | Grafo dirigido con pesos (ver formatos abajo). |
| `origen`       | `str`                 | Sí | Nodo de inicio. Debe existir en el grafo. |
| `destino`      | `str`                 | Sí | Nodo objetivo. Debe existir en el grafo. |
| `limite_nodos` | `int` (≥ 1)           | No | Máximo de nodos a visitar. **Por defecto: 80 % del total** (`ceil(0.8 · N)`). |
| `nodos`        | `list[str]`           | No | Etiquetas de los nodos cuando `grafo` es una matriz (por defecto `"0"`, `"1"`, …). |
| `coordenadas`  | `dict[str, [x, y]]`   | No | Posición de cada nodo para la heurística euclidiana. Si se omite, se generan automáticamente. |

**Formato 1: lista de adyacencia con pesos** (el de los archivos de la actividad)

```json
{
  "grafo": {
    "A": [["B", 15], ["C", 22]],
    "B": [["C", 5]],
    "C": []
  },
  "origen": "A",
  "destino": "C"
}
```

Cada entrada `"X": [["Y", w], ...]` significa una arista dirigida X → Y con peso `w`.

**Formato 2: matriz de adyacencia con pesos**

```json
{
  "grafo": [[0, 5, 9, 0],
            [0, 0, 3, 8],
            [0, 0, 0, 4],
            [0, 0, 0, 0]],
  "nodos": ["A", "B", "C", "D"],
  "origen": "A",
  "destino": "D",
  "limite_nodos": 4
}
```

`grafo[i][j] = w` es una arista de `nodos[i]` a `nodos[j]`; `0` significa que no hay arista.

**Validaciones** (error `422` si no se cumplen):

- El grafo no puede estar vacío; la matriz debe ser cuadrada.
- Toda arista debe apuntar a un nodo existente.
- Los pesos deben ser positivos (en la matriz, `0` = sin arista y los negativos se rechazan).
- `origen` y `destino` deben existir en el grafo.
- Si se envían `coordenadas`, deben cubrir todos los nodos.
- Si hay aristas paralelas entre el mismo par de nodos, se conserva la de menor peso.

Internamente, ambos formatos se normalizan a `{nodo: {vecino: peso}}`.

### Heurística: distancia euclidiana

Ambos algoritmos usan

```
h(n) = √((xₙ − x_destino)² + (yₙ − y_destino)²)
```

Los grafos de la actividad **no incluyen coordenadas**, así que cuando el cliente no las envía se generan de forma determinística:

1. Se acomodan los nodos en capas: `x` = saltos mínimos desde los nodos sin aristas entrantes; `y` = posición dentro de la capa.
2. Se escala todo por `min(peso / distancia)` sobre todas las aristas, de modo que la distancia euclidiana entre dos nodos conectados **nunca supere el peso de la arista**.

Con esto h(n) es **admisible y consistente**, por lo que A\* conserva su optimalidad. La contrapartida es que la heurística resulta débil y A\* se comporta cerca de Dijkstra. Si cuentas con coordenadas reales, envíalas en el campo `coordenadas` para mejorar la guía de la búsqueda.

### Búsqueda voraz (`greedy_search`)

- **Criterio de selección:** `f(n) = h(n)`. Siempre se expande el nodo de la frontera con menor distancia euclidiana al destino.
- Ignora el costo acumulado `g(n)`, por eso es rápida pero **no garantiza la ruta óptima**.
- La frontera es una cola de prioridad (`heapq`); los empates se resuelven por orden de descubrimiento.
- Cada nodo entra a la frontera una sola vez (se marca al descubrirlo) y se guarda su padre para reconstruir la ruta.

### Búsqueda A\* (`star_search`)

- **Función de valor:** `f(n) = g(n) + h(n)`, donde `g(n)` es el costo acumulado conocido desde el origen y `h(n)` la distancia euclidiana al destino.
- Si se encuentra un camino mejor hacia un nodo ya descubierto, se actualiza `g` y el padre, y se inserta de nuevo en la frontera; la entrada vieja se descarta al extraerla (eliminación perezosa).
- Con `h` admisible y consistente, la primera vez que se extrae el destino la ruta es **óptima**.

### Límite de nodos y definición de "visitado"

Un nodo se considera **visitado** cuando se extrae de la frontera para expandirlo (el destino cuenta). Antes de cada extracción se revisa el límite: si ya se visitaron `limite_nodos` nodos sin llegar al destino, la búsqueda se detiene y devuelve `solucion: false` con ruta vacía. Esto significa que `solucion: false` puede deberse al **límite**, no a que no exista camino.

---

## Endpoints

| Método | Ruta             | Algoritmo                      |
|--------|------------------|--------------------------------|
| POST   | `/search/greedy` | Búsqueda voraz (Greedy Best-First) |
| POST   | `/search/star`   | Búsqueda A\*                   |

Ambos reciben el mismo cuerpo (`EntradaBusqueda`) y devuelven el mismo formato.

### Ejemplo con `curl`

```bash
curl -X POST http://127.0.0.1:8000/search/star \
  -H "Content-Type: application/json" \
  -d '{
        "grafo": {"A": [["B", 15], ["C", 22]], "B": [["C", 5]], "C": []},
        "origen": "A",
        "destino": "C"
      }'
```

---

## Formato de respuesta

```json
{
  "nodos_visitados": 4,
  "solucion": true,
  "ruta": ["C", "E", "I"],
  "costo_ruta": 45.0,
  "T_n": {
    "medido": { "operaciones": 15, "tiempo_ms": 0.0209 },
    "teorico": "O(b^d)"
  },
  "S_n": {
    "medido": { "max_frontera": 3, "max_nodos_en_memoria": 7 },
    "teorico": "O(b^d)"
  }
}
```

| Campo             | Descripción |
|-------------------|-------------|
| `nodos_visitados` | Total de nodos visitados (expandidos), incluido el destino si se alcanzó. |
| `solucion`        | `true` si se llegó al destino dentro del límite; `false` en caso contrario. |
| `ruta`            | Lista ordenada de nodos del origen al destino (`[]` si no hay solución). |
| `costo_ruta`      | Suma de los pesos de la ruta (`null` si no hay solución). Campo adicional a los pedidos. |
| `T_n`             | Complejidad temporal: valor **medido** y cota **teórica**. |
| `S_n`             | Complejidad espacial: valor **medido** y cota **teórica**. |

### T(n) y S(n)

- **T(n) medido:**
  - `operaciones` = extracciones de la frontera + inserciones en la frontera + aristas evaluadas.
  - `tiempo_ms` = tiempo de reloj de la búsqueda.
- **S(n) medido:**
  - `max_frontera` = tamaño máximo que alcanzó la frontera.
  - `max_nodos_en_memoria` = máximo de (frontera + nodos ya visitados) en un instante.
- **Teórico:** voraz `O(b^m)` en tiempo y espacio (en el peor caso); A\* `O(b^d)` en tiempo y espacio. `b` = factor de ramificación, `m` = profundidad máxima del espacio de búsqueda, `d` = profundidad de la solución óptima. Con la implementación sobre montículo binario en un grafo finito, el costo práctico es del orden de `O((V + E) log V)`.

---

## Resultados de las pruebas

3 escenarios por grafo, con distintos orígenes y destinos. Límite = 80 % de los nodos (8, 20 y 40). "Visit." = nodos visitados.

### Grafo de 10 nodos (límite 8)

| Origen → Destino | Voraz: visit. / costo / ruta | A\*: visit. / costo / ruta |
|------------------|------------------------------|----------------------------|
| A → J | 4 / 90 / A→D→G→J | 8 / sin solución (límite alcanzado) |
| C → I | 3 / 45 / C→E→I | 4 / 45 / C→E→I |
| D → H | 3 / 68 / D→F→H | 6 / 68 / D→F→H |

### Grafo de 25 nodos (límite 20)

| Origen → Destino | Voraz: visit. / costo / ruta | A\*: visit. / costo / ruta |
|------------------|------------------------------|----------------------------|
| A → Y | 8 / 288 / A→D→F→H→N→T→W→Y | 19 / 115 / A→D→F→K→R→U→Y |
| B → X | 16 / 198 / B→G→F→M→P→X | 20 / sin solución (límite alcanzado) |
| C → T | 10 / 154 / C→J→L→Q→R→T | 13 / 140 / C→J→M→R→T |

### Grafo de 50 nodos (límite 40)

| Origen → Destino | Voraz: visit. / costo / ruta | A\*: visit. / costo / ruta |
|------------------|------------------------------|----------------------------|
| A → AX | 21 / 224 / A→C→M→V→AF→AL→AU→AX | 20 / 181 / A→F→K→R→AD→AM→AV→AX |
| E → AC | 5 / 108 / E→O→P→AC | 6 / 108 / E→O→P→AC |
| D → AH | 5 / 160 / D→L→U→AG→AH | 7 / 160 / D→L→U→AG→AH |

### Análisis

- **La voraz visita menos nodos** (casi siempre), porque solo mira la distancia estimada al destino. Su costo es que la ruta puede ser mucho más cara: en el grafo de 25 nodos, A → Y cuesta **288** con la voraz contra **115** con A\*.
- **A\* encuentra la ruta óptima** cuando termina, y nunca devolvió una ruta peor que la voraz. En los casos en que ambos coinciden en costo (C → I, D → H, E → AC, D → AH), la ruta es la misma.
- **A\* no encontró solución en dos casos** (grafo-10 A → J y grafo-25 B → X). No es que no exista camino: con una heurística débil, A\* necesita explorar más nodos para garantizar la ruta óptima y agota el límite del 80 % antes de extraer el destino. La voraz sí llegó en ambos casos, pero con rutas no óptimas.
- Con coordenadas reales (heurística más informada), A\* reduciría el número de nodos visitados.

---

## Notas

- Los grafos se tratan como **dirigidos**.
- Los pesos deben ser estrictamente positivos.
- Los tiempos en milisegundos varían entre ejecuciones; los nodos visitados, rutas y costos son determinísticos.
