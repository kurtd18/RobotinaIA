# ADR-001 - Proveedor de Datos

## Estado

Propuesto

---

## Contexto

RobotinaIA necesitará consultar información del mercado financiero.

No queremos depender de un único proveedor porque:

- las APIs pueden cambiar;
- algunas son de pago;
- otras tienen límites de uso.

---

## Decisión

Todo acceso al mercado se realizará mediante una interfaz común.

De esta forma será posible cambiar el proveedor de datos sin modificar el resto del sistema.

Ejemplos de proveedores:

- Yahoo Finance
- Twelve Data
- Alpha Vantage
- Polygon
- BVC (si existe integración disponible)

---

## Consecuencia

RobotinaIA será independiente del proveedor de datos.