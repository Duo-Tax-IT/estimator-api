// Link to a property's CoreLogic RP Data page. Reuse anywhere a property id is shown.
export default function RpDataLink({ rpId, children = "RP Data", className = "" }) {
  if (!rpId) return null;
  return (
    <a href={`https://rpp.corelogic.com.au/property/${rpId}`} target="_blank" rel="noreferrer"
      className={`text-primary hover:underline ${className}`}>
      {children}
    </a>
  );
}
