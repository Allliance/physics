import numpy as np
import matplotlib.pyplot as plt

a0 = 3.52
theta = 3.5*np.pi/180
a_M = a0/(2*np.sin(theta/2))
g1 = 4*np.pi/(np.sqrt(3)*a_M)
sigma_0 = np.array([[1,0],[0,1]])
P_t = np.array([[0,0],[0,1]])
P_b = np.array([[1,0],[0,0]])
sigma_p = np.array([[0,1],[0,0]])
sigma_m = np.array([[0,0],[1,0]])
psi = -105.9*np.pi/180
V = 16.5e-3
w = -18.8e-3
# kinetic = 6.34997
kinetic = 6.34997*2


# a0 = 3.472
# theta = 1.2*np.pi/180
# a_M = a0/(2*np.sin(theta/2))
# g1 = 4*np.pi/(np.sqrt(3)*a_M)
# sigma_0 = np.array([[1,0],[0,1]])
# P_t = np.array([[0,0],[0,1]])
# P_b = np.array([[1,0],[0,0]])
# sigma_p = np.array([[0,1],[0,0]])
# sigma_m = np.array([[0,0],[1,0]])
# psi = -89.6*np.pi/180
# V = 8.0e-3
# w = -8.5e-3

def ops(N):
    d = 2*N + 1
    x = np.arange(d) - N
    I  = np.eye(d, dtype=complex)
    X = np.diag(x.astype(float))
    S  = np.diag(np.ones(d-1), 1)         # shift by +1
    S2  = np.diag(np.ones(d-2), 2)        # shift by +2
    return I, X, S, S2
    
def H_V(N):
    # hop (n,m) --> (n+1, m) or (n,m) --> (n, m+1) or (n,m) --> (n-1, m-1) with phase factor np.exp(1j*psi)
    # hop (n,m) --> (n-1, m) or (n,m) --> (n, m-1) or (n,m) --> (n+1, m+1) with phase factor np.exp(1j*psi)
    
    I, _, S, S2 = ops(N)
    H = np.zeros(((2*N+1)**2*2, (2*N+1)**2*2), dtype=complex)
    sigma_0 = np.eye(2)
    
    # hopping by ±g1 corresponds to (n,m) --> (n±1,m)
    H += V * np.kron(np.kron(S.T, I), P_b) * np.exp(1j*psi)
    H += V * np.kron(np.kron(S, I), P_b) * np.exp(-1j*psi)
    H += V * np.kron(np.kron(S.T, I), P_t) * np.exp(-1j*psi)
    H += V * np.kron(np.kron(S, I), P_t) * np.exp(1j*psi)
    # hopping by ±g2 corresponds to (n,m) --> (n,m±1)
    H += V * np.kron(np.kron(I, S.T), P_b) * np.exp(1j*psi)
    H += V * np.kron(np.kron(I, S), P_b) * np.exp(-1j*psi)
    H += V * np.kron(np.kron(I, S.T), P_t) * np.exp(-1j*psi)
    H += V * np.kron(np.kron(I, S), P_t) * np.exp(1j*psi)
    # hopping by ±g3 corresponds to (n,m) --> (n±(-1),m±(-1))
    H += V * np.kron(np.kron(S, S), P_b) * np.exp(1j*psi)
    H += V * np.kron(np.kron(S.T, S.T), P_b) * np.exp(-1j*psi)
    H += V * np.kron(np.kron(S, S), P_t) * np.exp(-1j*psi)
    H += V * np.kron(np.kron(S.T, S.T), P_t) * np.exp(1j*psi)
    
    return H
    
def H_w(N):
    
    I, _, S, S2 = ops(N)
    H = np.zeros(((2*N+1)**2*2, (2*N+1)**2*2), dtype=complex)
    
    # 1 term -- (n,m) --> (n, m)
    H += w * np.kron(np.kron(I, I), sigma_p)
    H += w * np.kron(np.kron(I, I), sigma_m)
    # exp(-i*g3*r) term -- (n,m) --> (n±(-1), m±(-1)) corresponding to ±g3
    H += w * np.kron(np.kron(S, S), sigma_p)
    H += w * np.kron(np.kron(S.T, S.T), sigma_m)
    # exp(i*g2*r) term -- (n,m) --> (n, m±1) corresponding to ±(-g2)
    H += w * np.kron(np.kron(I, S), sigma_p)
    H += w * np.kron(np.kron(I, S.T), sigma_m)
    
    return H
    
    
def H_parab(N, kx, ky):
 	
	I, X, _, _ = ops(N)
	H = np.zeros(((2*N+1)**2*2, (2*N+1)**2*2), dtype=complex)
	
	H += (kx*kx + ky*ky) * np.kron(np.kron(I,I),P_b)
	H -= 2 * g1 * kx * np.kron(np.kron(X,I),P_b)
	H += g1 * (kx - np.sqrt(3)*ky) * np.kron(np.kron(I,X),P_b)
	H += g1**2 * (np.kron(np.kron(X**2,I),P_b) + np.kron(np.kron(I,X**2),P_b))
	H -= g1**2 * np.kron(np.kron(X,X),P_b)
	
	ky += g1 / np.sqrt(3)
	H += (kx*kx + ky*ky) * np.kron(np.kron(I,I),P_t)
	H -= 2 * g1 * kx * np.kron(np.kron(X,I),P_t)
	H += g1 * (kx - np.sqrt(3)*ky) * np.kron(np.kron(I,X),P_t)
	H += g1**2 * (np.kron(np.kron(X**2,I),P_t) + np.kron(np.kron(I,X**2),P_t))
	H -= g1**2 * np.kron(np.kron(X,X),P_t)
	
	return -kinetic * H


def hamiltonian(N, kx, ky):
    _, X, S, S2 = ops(N)
    _, X, S, S2 = ops(N)
    sigma_0 = np.eye(2)
    
    H = H_parab(N, kx, ky)
    
    H += H_V(N)
    
    H += H_w(N)
    
    return H

def dH_dkx(N, kx, ky):
	I, X, _, _ = ops(N)
	
	dH = np.zeros(((2*N+1)**2*2, (2*N+1)**2*2), dtype=complex)
	
	dH += -2 * kinetic * kx * np.kron(np.kron(I, I), sigma_0)
	dH += +2 * kinetic * g1 * np.kron(np.kron(X, I), sigma_0)
	dH += -2 * kinetic * g1/2 * np.kron(np.kron(I, X), sigma_0)
	
	return dH

def dH_dky(N, kx, ky):
	I, X, _, _ = ops(N)
	
	dH = np.zeros(((2*N+1)**2*2, (2*N+1)**2*2), dtype=complex)
	
	dH += -2 * kinetic * ky * np.kron(np.kron(I, I), sigma_0)
	dH += +2 * kinetic * g1*np.sqrt(3)/2 * np.kron(np.kron(I, X), sigma_0)
	dH += -2 * kinetic * g1/np.sqrt(3) * np.kron(np.kron(I, I), P_t)
	
	return dH
	
def berry_curvature(N, m, kx, ky, descending=True):
    """
    Berry curvature Omega_xy of band m at (kx, ky).
    descending=True  -> m=0 is the highest-energy band (top valence band here,
                        since the kinetic prefactor -kinetic makes the spectrum
                        unbounded below).
    descending=False -> m=0 is the lowest eigenvalue.
    """
    H = hamiltonian(N, kx, ky)
    E, U = np.linalg.eigh(H)                  # ascending, U[:, n] = |n>
    if descending:
        E = E[::-1]
        U = U[:, ::-1]

    vx = U.conj().T @ dH_dkx(N, kx, ky) @ U   # vx[m, n] = <m|dH/dkx|n>
    vy = U.conj().T @ dH_dky(N, kx, ky) @ U

    dE = E[m] - E
    mask = np.arange(E.size) != m

    num = vx[m, mask] * vy[mask, m]
    return -2.0 * np.imag(np.sum(num / dE[mask]**2))
    
def chern_number(N, m, nk=128):
    b1 = g1 * np.array([1.0, 0.0])
    b2 = g1 * np.array([-0.5, np.sqrt(3)/2])
    s = (np.arange(nk) + 0.5) / nk
    total = 0.0
    for u in s:
        for v in s:
            k = u*b1 + v*b2
            total += berry_curvature(N, m, k[0], k[1])
    dA = abs(b1[0]*b2[1] - b1[1]*b2[0]) / nk**2
    return total * dA / (2*np.pi)

def quantum_metric(N, m, kx, ky, descending=True):
    """2x2 metric g_ab = Re sum_{n!=m} <m|dH_a|n><n|dH_b|m> / (E_m-E_n)^2."""
    H = hamiltonian(N, kx, ky)
    E, U = np.linalg.eigh(H)
    if descending:
        E = E[::-1]; U = U[:, ::-1]
    vx = U.conj().T @ dH_dkx(N, kx, ky) @ U
    vy = U.conj().T @ dH_dky(N, kx, ky) @ U
    mask = np.arange(E.size) != m
    v = np.array([vx[m, mask], vy[m, mask]]) / abs(E[m] - E[mask])
    return np.real(v @ v.conj().T)

def metric_trace_integral(N, m, L=60, descending=True):
    b1 = g1 * np.array([1.0, 0.0])
    b2 = g1 * np.array([0.5, np.sqrt(3)/2])
    s = np.arange(L)
    total = 0.0
    for l1 in s:
        for l2 in s:
            k = (l1/L-1/2)*b1 + (l2/L-1/2)*b2
            total += np.trace(quantum_metric(N, m, k[0], k[1], descending))
    dA = abs(b1[0]*b2[1] - b1[1]*b2[0]) / L**2
    return total * dA