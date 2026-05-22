export default function ProjectLoading() {
  return (
    <div className='flex h-screen w-screen overflow-hidden bg-[#1a1a1a]'>
      {/* Skeleton Sidebar */}
      <div className='w-[280px] h-full shrink-0 border-r border-white/5 bg-[#1a1a1a] flex flex-col p-4'>
        <div className='h-8 w-1/2 bg-white/5 rounded-lg mb-8 animate-pulse'></div>
        <div className='flex flex-col gap-2'>
          <div className='h-10 w-full bg-white/5 rounded-lg animate-pulse'></div>
          <div className='h-10 w-full bg-white/5 rounded-lg animate-pulse'></div>
          <div className='h-10 w-full bg-white/5 rounded-lg animate-pulse'></div>
        </div>
      </div>
      
      {/* Skeleton Main Content */}
      <main className='flex flex-col flex-1 min-w-0 min-h-0'>
        {/* Skeleton Header */}
        <header className='flex items-center gap-2 px-4 py-3 shrink-0 border-b border-white/5 bg-[#1a1a1a]'>
          <div className='h-8 w-8 bg-white/5 rounded-lg animate-pulse'></div>
          <div className='h-8 w-8 bg-white/5 rounded-lg animate-pulse'></div>
          <div className='flex-1 flex justify-center'>
            <div className='h-4 w-48 bg-white/5 rounded-full animate-pulse'></div>
          </div>
          <div className='h-8 w-8 bg-white/5 rounded-full ml-2 animate-pulse'></div>
        </header>
        
        {/* Skeleton Chat Area */}
        <div className='flex-1 flex flex-col justify-end p-4 pb-8 space-y-6'>
           <div className='flex flex-col gap-3 items-start animate-pulse'>
             <div className='h-20 w-3/4 max-w-lg bg-white/5 rounded-2xl rounded-bl-sm'></div>
             <div className='h-12 w-1/2 bg-white/5 rounded-2xl rounded-bl-sm'></div>
           </div>
           <div className='flex flex-col gap-3 items-end animate-pulse'>
             <div className='h-12 w-1/3 max-w-sm bg-emerald-600/10 rounded-2xl rounded-br-sm'></div>
           </div>
           
           {/* Skeleton Input */}
           <div className='w-full max-w-3xl mx-auto mt-6 animate-pulse'>
             <div className='h-14 w-full bg-white/5 rounded-2xl border border-white/10'></div>
           </div>
        </div>
      </main>
    </div>
  );
}
