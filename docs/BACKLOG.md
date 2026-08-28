# RobotinaIA - Product Backlog

## Épica 1 - Mercado

- [ ] Conectar a un proveedor de datos real.
- [ ] Consultar el precio de una acción.
- [ ] Consultar varias acciones.
- [ ] Descargar histórico de precios.

## Épica 2 - Portafolio

- [ ] Registrar compras.
- [ ] Registrar ventas.
- [ ] Calcular costo promedio.
- [ ] Calcular rentabilidad.

## Épica 3 - Análisis Técnico

- [ ] RSI.
- [ ] MACD.
- [ ] EMA.
- [ ] SMA.
- [ ] Bandas de Bollinger.

## Épica 4 - Noticias

- [ ] Consultar noticias.
- [ ] Clasificar impacto.

## Épica 5 - Inteligencia Artificial

- [ ] Explicar recomendaciones.
- [ ] Detectar oportunidades.
- [ ] Detectar riesgos.

## Épica 6 - Dashboard

- [ ] Ventana principal.
- [ ] Gráficos.
- [ ] Panel del portafolio.
- [ ] Panel de alertas.
## Épica 7 - Estadísticas y Rendimiento

- [ ] Calcular ganó/perdió real por señal. Dos enfoques posibles:
      A) Comparar precio de la señal vs. precio de mercado tiempo después (más simple, no depende del portafolio - ver lógica rescatada de update_signals_legacy.py).
      B) Relacionar señal ejecutada con la posición de portafolio real que generó (más preciso, más trabajo).
- [ ] Win rate real basado en el resultado elegido arriba.
## Épica 8 - Infraestructura de Base de Datos

- [ ] Configurar Alembic correctamente cuando el esquema necesite modificar columnas existentes o al migrar a PostgreSQL (ya está en requirements.txt pero sin configurar).
## Épica 9 - Abstracción de Proveedor de Datos (ADR-001)

- [ ] Crear YahooProvider real (implementa MarketDataProvider con datos de yfinance, no mock).
- [ ] Migrar scoring.py para usar el provider en vez de llamar a yfinance directamente.
- [ ] Evaluar agregar un segundo provider (Twelve Data / Alpha Vantage) para probar que el cambio de proveedor no requiere tocar el resto del sistema.

## Épica 10 - Tests Reales

- [ ] Reescribir tests/test_score.py como prueba real (con assert) contra scoring.calcular_score(), no contra el ScoreEngine desactualizado que se eliminó.
- [ ] Convertir el resto de tests/*.py (sin ningún assert hoy) en pruebas automatizadas reales.
## Épica 12 - Trailing Stop (Stop Loss Dinámico)

- [x] /buy simplificado: calcula stop (-1%) y objetivo (+3%) automáticamente desde el precio de la señal.
- [x] Trailing stop: al alcanzar el objetivo, ese nivel se convierte en el nuevo stop y el objetivo sube otro 3%, sin vender.
- [x] Alerta con opciones (/vender, /mantener) cuando el precio toca el stop loss, sin cerrar la posición sola.
- [x] Decisión (vender/mantener) registrada en portfolio_decisions, consultable después.
- [x] Aviso de variación % desde la compra en cada ciclo, mientras la posición esté abierta. Se detiene solo al cerrarse.
- [ ] Definir qué hacer con la posición de BTC-USD que ya estaba muy por debajo del stop antes de esta funcionalidad.
## Épica 10 - Tests Reales (cerrada)

- [x] test_score.py reescrito contra scoring.calcular_score() real, con datos sintéticos y assert.
- [x] test_alert.py reescrito contra AlertEngine real, con assert.
- [x] test_env.py, test_telegram.py, test_yfinance.py movidos a scripts/ como chequeos manuales (check_env.py corregido para no imprimir credenciales reales).
- [x] test_gemini.py y test_openai.py eliminados (no hay ninguna funcionalidad real conectada a ninguno de los dos).
## Épica 13 - Limpieza de infraestructura (cerrada)

- [x] requirements.txt curado de un volcado completo de pip freeze (UTF-16, cientos de paquetes) a las 11 dependencias reales del proyecto, en UTF-8. Validado instalando en un venv nuevo desde cero.
- [x] Base de datos vacía duplicada (database/robotinaia.db) y carpetas sueltas sin uso (config/, data/, reports/) eliminadas.
## Épica 14 - Lista de activos ampliada (BVC oficial + MGC)

- [x] Reemplazada la lista de 10 activos por la lista oficial de 66 instrumentos listados en BVC/MGC que proporcionó el usuario.
- [x] Verificados contra Yahoo Finance real con scripts/watchlist_scanner.py: 63 de 66 confirmados funcionando.
- [x] Corregidos: BRK.B->BRK-B, ENEL->ENEL.MI, FALABELLA->FALABELLA.SN, CENCOSUD->CENCOSUD.SN, los 8 ETF (sufijo "CO" de MGC no existe en Yahoo, se usa el ticker base + bolsa real, mayormente .L de Londres).
- [x] Quitados: BCOLOMBIA/PFBCOLOM (Bancolombia se renombró a Grupo Cibest, duplicaban CIBEST/PFCIBEST), AVVILLAS, DAVIVIENDA (sin datos en Yahoo), CLH (Cemex Latam Holdings deslistada de la BVC en abril 2023).
- [ ] Identificar el ticker real de ICHN ("ETF China Large Caps" en la tabla original) y agregarlo.
- [ ] Con 63 activos el ciclo de scoring tarda más (~1 min+ por ciclo) - vigilar que siga corriendo bien dentro del intervalo de 15 min.
- [ ] Identificar el ticker real de ICHN ("ETF China Large Caps" en la tabla original) y agregarlo.
- [x] Bug encontrado y corregido: activos de baja liquidez con pocas velas hacían que pandas_ta devolviera None en MACD/RSI/EMA/ATR, y scoring.py tronaba con TypeError al compararlos. Corregido con comparación segura (_mayor_que) que trata datos faltantes como "condición no cumplida".
- [x] Con 63 activos el ciclo de scoring corre en ~17 segundos, bien dentro del intervalo de 15 min.
- [x] Bug encontrado (comparando contra análisis técnico real de un bróker): el criterio de ATR usaba un umbral fijo (30) sin relación a la escala de precio del activo, dando ventaja artificial a activos con precio nominal alto (CIBEST ~83,500) sobre otros de precio nominal bajo (ECOPETROL ~2,500), sin importar su volatilidad real. Corregido a ATR relativo (% del precio), calibrado con datos reales de 4 activos (AAPL, BTC-USD, MINEROS.CL, ECOPETROL.CL) el 28/07/2026 en 0.3%. Diagnóstico creado en scripts/diagnostico_score.py para auditar cualquier activo. Umbral sujeto a recalibrar con más evidencia.
## Épica 15 - Indicadores nuevos (Momentum + Bollinger)

- [x] Agregado Momento14 (velocidad del movimiento de precio) al scoring, +15 puntos.
- [x] Conectado Bollinger (ruptura de banda superior) al scoring, +10 puntos. Ya estaba programado desde hace varias sesiones, solo faltaba usarlo.
- [x] Pesos rebalanceados para que la suma máxima siga siendo 100 (VWAP 30->20, Volumen 25->15, EMA 15->10).
- [x] scripts/diagnostico_score.py actualizado con los 2 criterios nuevos.
- [ ] Pendiente (decisión de arquitectura, no urgente): agregar RSI/medias móviles de varios plazos (7/21/50/200 como los usa el bróker) requiere primero decidir si se usan datos diarios en vez de velas de 5 minutos para los indicadores de plazo largo - hoy "200 periodos" serían ~16 horas, no 200 días.
- [ ] Estocástico y Williams %R evaluados y descartados por ahora (redundantes con RSI, miden lo mismo con otra fórmula).
## Épica 16 - Despliegue en Railway (cerrada)

- [x] run_all.py: scheduler + bot en un solo proceso, comparten la misma base de datos.
- [x] DATABASE_PATH configurable por variable de entorno, volumen persistente montado en /data.
- [x] .gitignore corregido (llevaba sesiones sin aplicarse), ramas develop/main sincronizadas (main estaba congelada desde antes de toda la limpieza de esta conversación).
- [x] Bug: variable DATABASE_PATH con un caracter de tabulacion invisible pegado al inicio, causaba sqlite3.OperationalError. Corregido escribiendo el valor a mano.
- [x] Bug: requirements.txt no tenia "schedule" (el curado inicial solo detecto imports a nivel de archivo, no los que estan dentro de una funcion como en main.py). Agregado schedule==1.2.2, validado en entorno limpio.
- [x] Confirmado con /ping y /portfolio que el sistema corre de forma independiente del PC del usuario.
## Épica 17 - Migración de confiabilidad (blueprint robotinaia-reliability-foundation)

- [x] Épicas 1-7 completas: bloqueo de seguridad (token filtrado, historial limpiado con git filter-repo), integridad/concurrencia de base de datos, proveedor de datos unificado (YahooProvider), portfolio y P&L unificados con comisiones honestas, máquina de estados de alertas persistida, supervisor del scheduler de acciones, y consolidación de comandos de Telegram + dashboard.
- [x] E8-T1: código muerto confirmado eliminado (scoring.py, stats.py, bollinger.py, tests/test_score.py).
- [x] E8-T2 (chequeo mecánico): cero imports de portfolio.py/telegram_commands.py/signal_manager.py en el código activo. Corregido en el camino: app/alerts/portfolio_alerts.py (nunca migrado en ninguna épica anterior) ahora usa portfolio_service; import circular resuelto moviendo TRAILING_STEP_PCT a Settings; app/notifications/commands.py ya no depende de signal_manager.py.
- [x] **Sign-off del operador (gate de observación E8-T2), 2026-08-26**: sistema unificado (portfolio_service.py + app/notifications/commands.py) desplegado en Railway y confirmado corriendo en producción desde el **2026-08-25** (commits E4-T3/E7-T1/E7-T2/E8-T2). Comando real `/portfolio` verificado en producción el 2026-08-26 ("No existen posiciones abiertas"). Ventana de observación de 7 días: **2026-08-25 a 2026-09-01**. E8-T3 (borrar portfolio.py, telegram_commands.py, signal_manager.py) queda bloqueado hasta cumplir esa fecha sin incidentes.
- [ ] E8-T3: pendiente de la ventana de observación de arriba.