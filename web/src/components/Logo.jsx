export default function Logo({ className = 'h-8 w-8', tiled = false }) {
  if (tiled) {
    return (
      <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden="true">
        <rect width="32" height="32" rx="8" fill="#0B1220" />
        <path
          d="M5.2 16C9.7 9.4 13.5 7 16 7s6.3 2.4 10.8 9c-4.5 6.6-8.3 9-10.8 9s-6.3-2.4-10.8-9Z"
          fill="#C8F54A"
        />
        <circle cx="16" cy="16" r="5.15" fill="#0B1220" />
        <path
          d="M13.7 16.15 15.6 18l3.75-4"
          stroke="#C8F54A"
          strokeWidth="1.85"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    )
  }
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <path
        d="M5.2 16C9.7 9.4 13.5 7 16 7s6.3 2.4 10.8 9c-4.5 6.6-8.3 9-10.8 9s-6.3-2.4-10.8-9Z"
        fill="#C8F54A"
      />
      <circle cx="16" cy="16" r="5.15" fill="#070A0D" />
      <path
        d="M13.7 16.15 15.6 18l3.75-4"
        stroke="#C8F54A"
        strokeWidth="1.85"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
