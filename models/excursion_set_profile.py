import numpy as np
import camb
from scipy.special import hyp2f1
from scipy.interpolate import InterpolatedUnivariateSpline
from models import EisensteinHu

class ExcursionSetProfile:
    """
    Class to calculate predicted void matter density profiles according to the model of Massara & Sheth, 1811.xxxx
    """

    def __init__(self, h, omega_m, omega_b, z=0, mnu=0.06, ns=0.965, omega_k=0,
                 npts=200, camb_accuracy=1, use_eisenstein_hu=False):
        """
        Initialise instance: this uses cosmo params provided to get an interpolation to the matter power spectrum
        """

        omch2 = (omega_m - omega_b) * h**2
        ombh2 = omega_b * h**2
        self.omega_m = omega_m
        self.omega_b = omega_b
        self.omega_l = 1 - omega_m - omega_k

        self.k = np.logspace(-4, np.log10(2), npts)
        self.use_eisenstein_hu = use_eisenstein_hu

        if self.use_eisenstein_hu:  # fast approximation to the matter power spectrum
            # primordial amplitude As value not important as will be normalised later
            ehu = EisensteinHu(h, self.omega_m, self.omega_b, ns=ns, As=2e-9)
            # matter power at redshift 0
            pk_EH_0 = ehu.get_pofk_EH(self.k)
            # build the spline interpolator
            self.pk_EH_spline = InterpolatedUnivariateSpline(self.k, pk_EH_0)

            # get the sigma8 value for this power spectrum
            self.s80_fiducial = ehu.compute_sigma80()
            self.s8z_fiducial = self.s80_fiducial * D
        else:   # use CAMB calculation instead
            pars = camb.CAMBparams()
            pars.set_accuracy(AccuracyBoost=camb_accuracy) # values <1 speed up calculation, >1 slow it down

            #This function sets up CosmoMC-like settings, with one massive neutrino and helium set using BBN consistency
            pars.set_cosmology(H0=100*h, ombh2=ombh2, omch2=omch2, mnu=mnu, omk=0)
            # primordial amplitude As value not important as will be normalised later
            pars.InitPower.set_params(As=2e-9, ns=ns, r=0)
            if z > 0:
                pars.set_matter_power(redshifts=[z, 0.], kmax=2.0)
            else:
                pars.set_matter_power(redshifts=[0.], kmax=2.0)

            #Linear power spectrum
            pars.NonLinear = camb.model.NonLinear_none
            results = camb.get_results(pars)
            if z > 0:
                self.s8z_fiducial, self.s80_fiducial = results.get_sigma8()
            else:
                self.s80_fiducial = results.get_sigma8()
                self.s8z_fiducial = self.s80_fiducial
            self.pk = camb.get_matter_power_interpolator(pars, nonlinear=False)

    def get_pofk(self, k, z):
        """
        returns P(k, z) using chosen calculation method
        """

        if self.use_eisenstein_hu:
            D = self.growth_factor(z)
            return self.pk_EH_spline(k) * D**2
        else:
            return self.pk.P(z, k)

    def set_normalisation(self, sigma8, z=0):
        """
        Set the normalisation of the power spectrum amplitude
        """
        if z==0:
            self.normalisation = (sigma8 / self.s80_fiducial)**2
        else:
            self.normalisation = (sigma8 / self.s8z_fiducial)**2

    def window_tophat(self, k, R):
        """
        Top hat window function in Fourier space
        """
        return 3.0 * (np.sin(k * R) - k * R * np.cos(k * R)) / (k * R)**3

    def window(self, k, R, Rx):
        """
        Top hat window function with additional exponential cutoff
        """
        return self.window_tophat(k, R) * np.exp(-(k * R / Rx)**2 / 2)

    def sj_pq(self, Rp, Rq, Rx, j=0):
        """
        Power spectrum variance cross term
        """
        kk, rp, rq = np.meshgrid(self.k, Rp, Rq)
        integrand = kk**(2 + 2 * j) * self.normalisation * self.get_pofk(kk, 0) * self.window(kk, rp, Rx) * \
                    self.window_tophat(kk, rq) / (2 * np.pi**2)
        return np.trapz(integrand, kk, axis=1)

    def sj_pp(self, Rp, Rx, j=0, Rq=None):
        """
        Power spectrum variance
        """
        kk, rp, rq = np.meshgrid(self.k, Rp, Rq)
        integrand = kk**(2 + 2 * j) * self.normalisation * self.get_pofk(kk, 0) * self.window(kk, rp, Rx)**2 / (2 * np.pi**2)
        return np.trapz(integrand, kk, axis=1)

    def sj_pp_ratio(self, Rp, Rx, Rq=None):
        """
        Ratio of sj_pp(j=0) / sj_pp(j=1) when both evaluated at the same Rp, Rx, Rq values
        This implementation is faster than using individual repeated calls to the method above
        """
        kk, rp, rq = np.meshgrid(self.k, Rp, Rq)
        window = self.window_tophat(kk, rp) * np.exp(-(kk * rp / Rx)**2 / 2)
        integrand0 = kk**2 * self.normalisation * self.get_pofk(kk, 0) * window**2 / (2 * np.pi**2)
        integrand1 = kk**2 * integrand0
        j_zero = np.trapz(integrand0, kk, axis=1)
        j_one = np.trapz(integrand1, kk, axis=1)

        return j_zero / j_one

    def s0_derivative_term(self, Rp, Rq, Rx):
        """
        Derivative ds_0^pq / ds_0^pp appearing in EST model for Lagrangian density profile
        """
        step = 0.01 * Rp
        rp = Rp + np.array([-2, -1, 1, 2]) * step
        deriv_sjpq = (-self.sj_pq(rp[3], Rq, Rx, 0) + 8 * self.sj_pq(rp[2], Rq, Rx, 0) - 8 *
                      self.sj_pq(rp[1], Rq, Rx, 0) + self.sj_pq(rp[0], Rq, Rx, 0)) / (12 * step)
        deriv_sjpp = (-self.sj_pp(rp[3], Rx, 0) + 8 * self.sj_pp(rp[2], Rx, 0) - 8 * self.sj_pp(rp[1], Rx, 0) +
                      self.sj_pp(rp[0], Rx, 0)) / (12 * step)
        return deriv_sjpq / deriv_sjpp

    def lagrangian_profile(self, Rq, b10, b01, Rp, Rx):
        """
        Lagrangian density profile around voids in the EST model
        """
        return b10 * self.sj_pq(Rp, Rq, Rx, 0) + b01 * 2 * self.sj_pp(Rp, Rx, 0) * self.s0_derivative_term(Rp, Rq, Rx)

    def growth_factor(self, z):
        """
        Linear growth factor D(z) at redshift z, normalised to unity at z=0
        """
        az = 1. / (1 + z)
        growth = az ** 2.5 * np.sqrt(self.omega_l + self.omega_m * az ** (-3.)) * \
                      hyp2f1(5. / 6, 3. / 2, 11. / 6, -(self.omega_l * az ** 3.) / self.omega_m) / \
                      hyp2f1(5. / 6, 3. / 2, 11. / 6, -self.omega_l / self.omega_m)
        return growth

    def eulerian_1halo(self, RqL, z, b10, b01, Rp, Rx, deltac=1.686):
        """
        Simple spherical evolution model for Eulerian matter profile of voids
        """
        one_halo = (1 - self.growth_factor(z) * self.lagrangian_profile(RqL, b10, b01, Rp, Rx) / deltac)**(-deltac) - 1
        eulerian_dist = RqL / (1 + one_halo)**(1/3)
        return eulerian_dist, one_halo

    def eulerian_2halo(self, RqE, Rp, Rx):
        """
        Extra term to Eulerian matter profile of voids arising from void motion
        """
        # faster
        bv = 1 - self.k**2 * self.sj_pp_ratio(Rp, Rx)
        # equivalent but slower
        # bv = 1 - self.k**2 * self.sj_pp(Rp, Rx, 0) / self.sj_pp(Rp, Rx, 1)
        integrand = bv * self.window(self.k, Rp, Rx) * self.window_tophat(self.k, RqE) * self.normalisation * \
                    self.get_pofk(self.k, 0) * self.k**2 / (2 * np.pi**2)
        return np.trapz(integrand, self.k)

    def eulerian_model_profiles(self, RqL, z, b10, b01, Rp, Rx, deltac=1.686):
        """
        Full model calculation of Eulerian matter profile around voids

        :param RqL: Lagrangian distance from the void centre at which to evaluate profile
        :param z: void redshift
        :param b10: bias nuisance parameter
        :param b01: other bias nuisance parameter
        :param Rp: smoothing scale on which voids are excursion set troughs in Lagrangian density field
        :param Rx: additional scale nuisance parameter

        Returns RqL, RqE, Delta(<RqE)
        """
        RqE, model_1halo = self.eulerian_1halo(RqL, z, b10, b01, Rp, Rx, deltac)
        RqE = RqE[0]; model_1halo = model_1halo[0]
        # check for NaNs in RqE and remove if necessary
        valid = np.logical_not(np.isnan(RqE))
        RqE = RqE[valid]; model_1halo = model_1halo[valid]
        model_2halo = np.zeros_like(RqE)
        for i, rqe in enumerate(RqE):
            model_2halo[i] = self.eulerian_2halo(rqe, Rp, Rx)
        model_full = model_1halo + self.growth_factor(z)**2 * model_2halo
        return RqL, RqE, model_full

    def delta(self, r, b10, b01, Rp, Rx, z, deltac=1.686):
        """
        Void-matter monopole delta(r)

        :param r: array of distances from void centre; roughly sets the range of radial distances for interpolation
        :param z: void redshift
        :param b10: bias nuisance parameter
        :param b01: other bias nuisance parameter
        :param Rp: smoothing scale on which voids are excursion set troughs in Lagrangian density field
        :param Rx: additional scale nuisance parameter

        Returns an interpolating function for delta(r) corresponding to modelled Eulerian matter density profile
        """
        RqL, RqE, model = self.eulerian_model_profiles(r, z, b10, b01, Rp, Rx, deltac)
        integ_delta = InterpolatedUnivariateSpline(RqE, model)
        deriv = np.gradient(integ_delta(r), r)
        delta = InterpolatedUnivariateSpline(r, integ_delta(r) + r * deriv / 3)
        return delta
