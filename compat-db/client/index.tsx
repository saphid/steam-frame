// No browser access to the data: Frame Control reads and writes it through the
// key-protected /v1 endpoints only.
export function App() {
  return (
    <main className="min-h-screen grid place-items-center bg-slate-900 text-slate-300 p-8">
      <p>Frame compatibility database. Private: only Frame Control can use it.</p>
    </main>
  );
}
