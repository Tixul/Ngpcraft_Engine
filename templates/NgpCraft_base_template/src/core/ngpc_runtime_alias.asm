$MAXIMUM

        module  ngpc_runtime_alias

        public  C9H_mullu, C9H_divlu, C9H_remlu
        extern  large _C9H_mullu, _C9H_divlu, _C9H_remlu

ALIAS   section code large

C9H_mullu:
        jp      _C9H_mullu

C9H_divlu:
        jp      _C9H_divlu

C9H_remlu:
        jp      _C9H_remlu

        end
